// TzServerPlugin.cs — AutoCAD 2025/TArch local bridge for Codex.
//
// Network requests are parsed on worker threads, but every AutoCAD API call is
// serialized onto AutoCAD's UI/idle context.  Writes may carry
// expected_document_id and expected_revision guards.  The bridge returns
// structured JSON and never reports SendStringToExecute as completed work.
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Threading;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.Colors;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.EditorInput;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Runtime;
using AcApplication = Autodesk.AutoCAD.ApplicationServices.Core.Application;
using Exception = System.Exception;

[assembly: ExtensionApplication(typeof(TzServer.TzServerPlugin))]

namespace TzServer
{
    public sealed class TzServerPlugin : IExtensionApplication
    {
        public const int BasePort = 45679;
        public const int PortSearchCount = 21;
        public const string ProtocolVersion = "2";
        public const string PluginVersion = "2.0.0";
        private const int MaxBodyBytes = 4 * 1024 * 1024;
        private const int CadDispatchTimeoutMs = 120000;

        private TcpListener _server;
        private int _port;
        private Thread _serverThread;
        private volatile bool _stopping;
        private readonly ConcurrentQueue<CadWorkItem> _cadQueue = new ConcurrentQueue<CadWorkItem>();
        private readonly ConcurrentDictionary<string, CommandJob> _jobs =
            new ConcurrentDictionary<string, CommandJob>(StringComparer.OrdinalIgnoreCase);
        private readonly object _revisionGate = new object();
        private readonly Dictionary<Database, long> _revisions = new Dictionary<Database, long>();
        private readonly HashSet<Document> _hookedDocuments = new HashSet<Document>();
        private readonly Dictionary<string, Dictionary<string, string>> _idempotency =
            new Dictionary<string, Dictionary<string, string>>(StringComparer.OrdinalIgnoreCase);

        private readonly int _processId = Process.GetCurrentProcess().Id;
        private readonly string _instanceId =
            Process.GetCurrentProcess().Id.ToString(CultureInfo.InvariantCulture) + "-" +
            Guid.NewGuid().ToString("N").Substring(0, 12);

        private static readonly string LogPath =
            Path.Combine(Path.GetTempPath(), "tzserver.log");

        private string DiscoveryPath
        {
            get
            {
                return Path.Combine(
                    Path.GetTempPath(),
                    "tzserver-" + _processId.ToString(CultureInfo.InvariantCulture) + ".json");
            }
        }

        public void Initialize()
        {
            Log("Initialize protocol=" + ProtocolVersion + " plugin=" + PluginVersion +
                " pid=" + _processId + " instance=" + _instanceId);
            AcApplication.Idle += OnApplicationIdle;
            try
            {
                Exception lastError = null;
                for (int candidate = BasePort; candidate < BasePort + PortSearchCount; candidate++)
                {
                    try
                    {
                        _server = new TcpListener(IPAddress.Loopback, candidate);
                        _server.Start();
                        _port = candidate;
                        lastError = null;
                        break;
                    }
                    catch (SocketException e)
                    {
                        lastError = e;
                        try { if (_server != null) _server.Stop(); } catch { }
                        _server = null;
                    }
                }
                if (_server == null)
                    throw new IOException(
                        "No free loopback port in " + BasePort + ".." +
                        (BasePort + PortSearchCount - 1), lastError);
                _serverThread = new Thread(RunServer)
                {
                    IsBackground = true,
                    Name = "TzServer-" + _port.ToString(CultureInfo.InvariantCulture)
                };
                _serverThread.Start();
                WriteDiscovery("listening", null);
                Log("Listening on 127.0.0.1:" + _port);
            }
            catch (Exception e)
            {
                _server = null;
                WriteDiscovery("port_conflict", e.Message);
                Log("Start failed: " + e);
            }
        }

        public void Terminate()
        {
            _stopping = true;
            try { AcApplication.Idle -= OnApplicationIdle; } catch { }
            try { if (_server != null) _server.Stop(); } catch { }
            while (_cadQueue.TryDequeue(out var pending))
            {
                pending.Result = Error("bridge_stopping", "TzServer is stopping");
                pending.Done.Set();
            }
            try { if (File.Exists(DiscoveryPath)) File.Delete(DiscoveryPath); } catch { }
        }

        private void RunServer()
        {
            while (!_stopping && _server != null)
            {
                TcpClient client;
                try { client = _server.AcceptTcpClient(); }
                catch { break; }
                ThreadPool.QueueUserWorkItem(_ => Handle(client));
            }
        }

        private void Handle(TcpClient client)
        {
            using (client)
            using (NetworkStream stream = client.GetStream())
            {
                try
                {
                    stream.ReadTimeout = 15000;
                    stream.WriteTimeout = 15000;
                    HttpRequest request = ReadRequest(stream);
                    string result = Dispatch(request);
                    WriteResponse(stream, result);
                }
                catch (Exception e)
                {
                    Log("Handle: " + e);
                    try { WriteResponse(stream, Error("bad_request", e.Message)); } catch { }
                }
            }
        }

        private static HttpRequest ReadRequest(NetworkStream stream)
        {
            var headerBytes = new List<byte>(1024);
            int matched = 0;
            byte[] terminator = { 13, 10, 13, 10 };
            while (headerBytes.Count < 65536)
            {
                int value = stream.ReadByte();
                if (value < 0) throw new IOException("Unexpected end of HTTP headers");
                byte b = (byte)value;
                headerBytes.Add(b);
                if (b == terminator[matched])
                {
                    matched++;
                    if (matched == terminator.Length) break;
                }
                else
                {
                    matched = b == terminator[0] ? 1 : 0;
                }
            }
            if (matched != terminator.Length) throw new IOException("HTTP header too large");

            string headerText = Encoding.ASCII.GetString(headerBytes.ToArray());
            string[] lines = headerText.Split(new[] { "\r\n" }, StringSplitOptions.None);
            string[] requestLine = lines[0].Split(' ');
            if (requestLine.Length < 2) throw new IOException("Malformed HTTP request line");

            int contentLength = 0;
            foreach (string line in lines.Skip(1))
            {
                int colon = line.IndexOf(':');
                if (colon <= 0) continue;
                string key = line.Substring(0, colon).Trim();
                string value = line.Substring(colon + 1).Trim();
                if (key.Equals("Content-Length", StringComparison.OrdinalIgnoreCase))
                    int.TryParse(value, NumberStyles.Integer, CultureInfo.InvariantCulture, out contentLength);
            }
            if (contentLength < 0 || contentLength > MaxBodyBytes)
                throw new IOException("Invalid or oversized Content-Length");

            byte[] bodyBytes = new byte[contentLength];
            int offset = 0;
            while (offset < contentLength)
            {
                int read = stream.Read(bodyBytes, offset, contentLength - offset);
                if (read <= 0) throw new IOException("Unexpected end of HTTP body");
                offset += read;
            }
            return new HttpRequest
            {
                Method = requestLine[0].ToUpperInvariant(),
                Path = requestLine[1].Trim('/').Split('?')[0].ToLowerInvariant(),
                Body = Encoding.UTF8.GetString(bodyBytes)
            };
        }

        private static void WriteResponse(NetworkStream stream, string json)
        {
            byte[] body = Encoding.UTF8.GetBytes(json ?? "{}");
            string head =
                "HTTP/1.1 200 OK\r\n" +
                "Content-Type: application/json; charset=utf-8\r\n" +
                "Content-Length: " + body.Length.ToString(CultureInfo.InvariantCulture) + "\r\n" +
                "Cache-Control: no-store\r\n" +
                "Connection: close\r\n\r\n";
            byte[] header = Encoding.ASCII.GetBytes(head);
            stream.Write(header, 0, header.Length);
            stream.Write(body, 0, body.Length);
        }

        private string Dispatch(HttpRequest request)
        {
            try
            {
                switch (request.Path)
                {
                    case "ping":
                    case "info":
                    case "state":
                        return OnCadThread(State);
                    case "new":
                        return OnCadThread(() => NewDocument(request.Body));
                    case "open":
                        return OnCadThread(() => OpenDocument(request.Body));
                    case "units":
                        return OnCadThread(() => SetUnits(request.Body));
                    case "layer":
                        return OnCadThread(() => SetLayer(request.Body));
                    case "textstyle":
                        return OnCadThread(() => SetTextStyle(request.Body));
                    case "draw":
                        return OnCadThread(() => Draw(request.Body));
                    case "batch":
                        return OnCadThread(() => ApplyBatch(request.Body));
                    case "edit":
                        return OnCadThread(() => Edit(request.Body));
                    case "entities":
                    case "query":
                        return OnCadThread(() => QueryEntities(request.Body));
                    case "select":
                        return OnCadThread(() => SelectEntities(request.Body));
                    case "validate":
                        return OnCadThread(() => ValidateDrawing(request.Body));
                    case "zoom":
                        return OnCadThread(() => Zoom(request.Body));
                    case "saveas":
                        return OnCadThread(() => SaveAs(request.Body));
                    case "save":
                        return OnCadThread(() => Save(request.Body));
                    case "command":
                        return OnCadThread(() => QueueCommand(request.Body));
                    case "job":
                        return JobStatus(request.Body);
                    case "lisp":
                        return Error(
                            "raw_lisp_disabled",
                            "Raw AutoLISP relay is disabled in protocol 2; use typed tools or an explicit command job.");
                    default:
                        return Error("unknown_endpoint", "Unknown endpoint: " + request.Path);
                }
            }
            catch (BridgeException e) { return Error(e.Code, e.Message); }
            catch (Exception e)
            {
                Log("Dispatch " + request.Path + ": " + e);
                return Error("cad_error", e.Message);
            }
        }

        private string OnCadThread(Func<string> action)
        {
            var item = new CadWorkItem { Action = action };
            _cadQueue.Enqueue(item);
            if (!item.Done.Wait(CadDispatchTimeoutMs))
            {
                return Serialize(new
                {
                    error = "AutoCAD main-context dispatch timed out",
                    code = "cad_busy",
                    protocol_version = ProtocolVersion,
                    plugin_version = PluginVersion,
                    process_id = _processId,
                    instance_id = _instanceId
                });
            }
            return item.Result;
        }

        private void OnApplicationIdle(object sender, EventArgs e)
        {
            while (_cadQueue.TryDequeue(out var item))
            {
                try { item.Result = item.Action(); }
                catch (BridgeException ex) { item.Result = Error(ex.Code, ex.Message); }
                catch (Exception ex)
                {
                    Log("CAD work item: " + ex);
                    item.Result = Error("cad_error", ex.Message);
                }
                finally { item.Done.Set(); }
            }
        }

        private Document ActiveDocument()
        {
            Document d = null;
            try { d = AcApplication.DocumentManager.MdiActiveDocument; } catch { }
            if (d != null) EnsureDocumentHooks(d);
            return d;
        }

        private void EnsureDocumentHooks(Document d)
        {
            if (d == null) return;
            lock (_revisionGate)
            {
                if (!_revisions.ContainsKey(d.Database)) _revisions[d.Database] = 0;
                if (_hookedDocuments.Contains(d)) return;
                _hookedDocuments.Add(d);
                Database db = d.Database;
                db.ObjectAppended += (_, __) => BumpRevision(db);
                db.ObjectModified += (_, __) => BumpRevision(db);
                db.ObjectErased += (_, __) => BumpRevision(db);
                d.CommandWillStart += (_, args) => UpdateCommandJob(d, args.GlobalCommandName, "running", null);
                d.CommandEnded += (_, args) => UpdateCommandJob(d, args.GlobalCommandName, "completed", null);
                d.CommandCancelled += (_, args) => UpdateCommandJob(d, args.GlobalCommandName, "cancelled", null);
                d.CommandFailed += (_, args) => UpdateCommandJob(d, args.GlobalCommandName, "failed", "AutoCAD command failed");
            }
        }

        private void BumpRevision(Database db)
        {
            lock (_revisionGate)
            {
                if (!_revisions.ContainsKey(db)) _revisions[db] = 0;
                _revisions[db]++;
            }
        }

        private long Revision(Document d)
        {
            EnsureDocumentHooks(d);
            lock (_revisionGate) return _revisions[d.Database];
        }

        private string DocumentId(Document d)
        {
            if (d == null) return null;
            return _instanceId + ":" + d.GetHashCode().ToString("X", CultureInfo.InvariantCulture);
        }

        private void CheckExpected(Document d, JsonElement root)
        {
            if (d == null) throw new BridgeException("no_document", "No active AutoCAD document");
            string expectedDocument = GetString(root, "expected_document_id");
            if (!string.IsNullOrWhiteSpace(expectedDocument) &&
                !expectedDocument.Equals(DocumentId(d), StringComparison.Ordinal))
            {
                throw new BridgeException(
                    "document_mismatch",
                    "Refusing write: expected document " + expectedDocument +
                    " but active document is " + DocumentId(d));
            }
            if (TryGetInt64(root, "expected_revision", out long expectedRevision))
            {
                long actual = Revision(d);
                if (expectedRevision != actual)
                {
                    throw new BridgeException(
                        "revision_mismatch",
                        "Refusing write: expected revision " + expectedRevision +
                        " but current revision is " + actual);
                }
            }
        }

        private string State()
        {
            Document d = ActiveDocument();
            var baseState = new Dictionary<string, object>
            {
                ["status"] = "ok",
                ["protocol_version"] = ProtocolVersion,
                ["plugin_version"] = PluginVersion,
                ["process_id"] = _processId,
                ["instance_id"] = _instanceId,
                ["port"] = _port,
                ["has_document"] = d != null,
                ["discovery_path"] = DiscoveryPath
            };
            if (d == null) return Serialize(baseState);

            Database db = d.Database;
            string currentLayer = "";
            int entityCount = 0;
            var byType = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
            var layerNames = new List<string>();
            var textStyleNames = new List<string>();
            using (DocumentLock docLock = d.LockDocument())
            using (Transaction tr = db.TransactionManager.StartOpenCloseTransaction())
            {
                var layer = tr.GetObject(db.Clayer, OpenMode.ForRead) as LayerTableRecord;
                currentLayer = layer != null ? layer.Name : "";
                var layerTable = tr.GetObject(db.LayerTableId, OpenMode.ForRead) as LayerTable;
                foreach (ObjectId layerId in layerTable)
                {
                    var layerRecord = tr.GetObject(layerId, OpenMode.ForRead) as LayerTableRecord;
                    if (layerRecord != null) layerNames.Add(layerRecord.Name);
                }
                var textStyleTable = tr.GetObject(db.TextStyleTableId, OpenMode.ForRead) as TextStyleTable;
                foreach (ObjectId styleId in textStyleTable)
                {
                    var styleRecord = tr.GetObject(styleId, OpenMode.ForRead) as TextStyleTableRecord;
                    if (styleRecord != null) textStyleNames.Add(styleRecord.Name);
                }
                var bt = tr.GetObject(db.BlockTableId, OpenMode.ForRead) as BlockTable;
                var model = tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead) as BlockTableRecord;
                foreach (ObjectId id in model)
                {
                    entityCount++;
                    var entity = tr.GetObject(id, OpenMode.ForRead, false) as Entity;
                    if (entity == null) continue;
                    string type = entity.GetRXClass().DxfName ?? entity.GetType().Name;
                    byType[type] = byType.TryGetValue(type, out int count) ? count + 1 : 1;
                }
            }

            string filePath = "";
            try { filePath = db.Filename ?? ""; } catch { }
            int dbmod = SafeSystemVariableInt("DBMOD");
            string cmdNames = SafeSystemVariableString("CMDNAMES");
            int commandActive = SafeSystemVariableInt("CMDACTIVE");
            var tarch = DetectTarch();

            baseState["document_id"] = DocumentId(d);
            baseState["document_name"] = d.Name;
            baseState["document_path"] = filePath;
            baseState["revision"] = Revision(d);
            baseState["dirty"] = dbmod != 0;
            baseState["dbmod"] = dbmod;
            baseState["units"] = db.Insunits.ToString();
            baseState["insunits_code"] = (int)db.Insunits;
            baseState["current_layer"] = currentLayer;
            baseState["layers"] = layerNames.OrderBy(name => name).ToArray();
            baseState["text_styles"] = textStyleNames.OrderBy(name => name).ToArray();
            baseState["modelspace_entities"] = entityCount;
            baseState["entity_counts"] = byType;
            baseState["command_active"] = commandActive;
            baseState["command_names"] = cmdNames;
            baseState["tarch"] = tarch;
            baseState["acad_version"] = SafeSystemVariableString("ACADVER");
            return Serialize(baseState);
        }

        private string NewDocument(string body)
        {
            JsonElement root = ParseObject(body);
            string template = GetString(root, "template");
            Document d = AcApplication.DocumentManager.Add(template ?? "");
            EnsureDocumentHooks(d);
            return Serialize(new
            {
                ok = true,
                document_id = DocumentId(d),
                document_name = d.Name,
                revision = Revision(d)
            });
        }

        private string OpenDocument(string body)
        {
            JsonElement root = ParseObject(body);
            string path = RequireString(root, "path");
            if (!File.Exists(path)) throw new BridgeException("path_not_found", "DWG not found: " + path);
            bool readOnly = GetBoolean(root, "read_only", false);
            Document d = AcApplication.DocumentManager.Open(Path.GetFullPath(path), readOnly);
            EnsureDocumentHooks(d);
            return Serialize(new
            {
                ok = true,
                document_id = DocumentId(d),
                document_name = d.Name,
                document_path = d.Database.Filename,
                revision = Revision(d),
                read_only = readOnly
            });
        }

        private string SetUnits(string body)
        {
            using (JsonDocument json = Parse(body))
            {
                JsonElement root = json.RootElement;
                Document d = ActiveDocument();
                CheckExpected(d, root);
                string unit = (GetString(root, "unit") ?? "mm").ToLowerInvariant();
                UnitsValue value;
                switch (unit)
                {
                    case "unitless": value = UnitsValue.Undefined; break;
                    case "inch":
                    case "inches": value = UnitsValue.Inches; break;
                    case "feet":
                    case "foot": value = UnitsValue.Feet; break;
                    case "mm": value = UnitsValue.Millimeters; break;
                    case "cm": value = UnitsValue.Centimeters; break;
                    case "m": value = UnitsValue.Meters; break;
                    case "km": value = UnitsValue.Kilometers; break;
                    default: throw new BridgeException("invalid_unit", "Unsupported unit: " + unit);
                }
                int precision = GetInt(root, "precision", 3);
                using (DocumentLock docLock = d.LockDocument())
                {
                    d.Database.Insunits = value;
                    AcApplication.SetSystemVariable("LUNITS", 2);
                    AcApplication.SetSystemVariable("LUPREC", Math.Max(0, Math.Min(8, precision)));
                }
                return Serialize(new
                {
                    ok = true,
                    document_id = DocumentId(d),
                    revision = Revision(d),
                    units = value.ToString(),
                    precision = precision
                });
            }
        }

        private string SetLayer(string body)
        {
            using (JsonDocument json = Parse(body))
            {
                JsonElement root = json.RootElement;
                Document d = ActiveDocument();
                CheckExpected(d, root);
                string name = RequireString(root, "name");
                bool setActive = GetBoolean(root, "set_active", false);
                Database db = d.Database;
                ObjectId layerId;
                bool created = false;
                using (DocumentLock docLock = d.LockDocument())
                using (Transaction tr = db.TransactionManager.StartTransaction())
                {
                    var table = tr.GetObject(db.LayerTableId, OpenMode.ForRead) as LayerTable;
                    LayerTableRecord record;
                    if (!table.Has(name))
                    {
                        table.UpgradeOpen();
                        record = new LayerTableRecord { Name = name };
                        layerId = table.Add(record);
                        tr.AddNewlyCreatedDBObject(record, true);
                        created = true;
                    }
                    else
                    {
                        layerId = table[name];
                        record = tr.GetObject(layerId, OpenMode.ForWrite) as LayerTableRecord;
                    }
                    if (root.TryGetProperty("color", out JsonElement color) &&
                        color.ValueKind == JsonValueKind.Number)
                    {
                        int index = color.GetInt32();
                        if (index < 1 || index > 255)
                            throw new BridgeException("invalid_color", "Layer color must be 1..255");
                        record.Color = Color.FromColorIndex(ColorMethod.ByAci, (short)index);
                    }
                    string linetype = GetString(root, "linetype");
                    if (!string.IsNullOrWhiteSpace(linetype) &&
                        !linetype.Equals("BYLAYER", StringComparison.OrdinalIgnoreCase))
                    {
                        var lt = tr.GetObject(db.LinetypeTableId, OpenMode.ForRead) as LinetypeTable;
                        if (!lt.Has(linetype))
                            throw new BridgeException("linetype_not_found", "Linetype is not loaded: " + linetype);
                        record.LinetypeObjectId = lt[linetype];
                    }
                    tr.Commit();
                }
                if (setActive) db.Clayer = layerId;
                return Serialize(new
                {
                    ok = true,
                    created = created,
                    name = name,
                    set_active = setActive,
                    current_layer = CurrentLayerName(d),
                    document_id = DocumentId(d),
                    revision = Revision(d)
                });
            }
        }

        private string SetTextStyle(string body)
        {
            using (JsonDocument json = Parse(body))
            {
                JsonElement root = json.RootElement;
                Document d = ActiveDocument();
                CheckExpected(d, root);
                string name = GetString(root, "name") ?? "hz";
                string font = GetString(root, "font") ?? "simsun.ttc";
                string bigFont = GetString(root, "bigfont") ?? "";
                double height = GetDouble(root, "height", 0.0);
                bool setActive = GetBoolean(root, "set_active", true);
                Database db = d.Database;
                ObjectId styleId;
                bool created = false;
                using (DocumentLock docLock = d.LockDocument())
                using (Transaction tr = db.TransactionManager.StartTransaction())
                {
                    var table = tr.GetObject(db.TextStyleTableId, OpenMode.ForRead) as TextStyleTable;
                    TextStyleTableRecord record;
                    if (!table.Has(name))
                    {
                        table.UpgradeOpen();
                        record = new TextStyleTableRecord { Name = name };
                        styleId = table.Add(record);
                        tr.AddNewlyCreatedDBObject(record, true);
                        created = true;
                    }
                    else
                    {
                        styleId = table[name];
                        record = tr.GetObject(styleId, OpenMode.ForWrite) as TextStyleTableRecord;
                    }
                    record.FileName = font;
                    record.BigFontFileName = bigFont;
                    record.TextSize = Math.Max(0.0, height);
                    tr.Commit();
                }
                if (setActive) db.Textstyle = styleId;
                return Serialize(new
                {
                    ok = true,
                    created = created,
                    name = name,
                    font = font,
                    bigfont = bigFont,
                    height = height,
                    set_active = setActive,
                    document_id = DocumentId(d),
                    revision = Revision(d)
                });
            }
        }

        private string Draw(string body)
        {
            using (JsonDocument json = Parse(body))
            {
                JsonElement root = json.RootElement;
                Document d = ActiveDocument();
                CheckExpected(d, root);
                var result = ApplyOperations(d, new[] { root }, true);
                var first = result.Items.First();
                return Serialize(new
                {
                    ok = true,
                    handle = first.Handle,
                    type = first.Type,
                    op_id = first.OpId,
                    document_id = DocumentId(d),
                    revision = Revision(d)
                });
            }
        }

        private string ApplyBatch(string body)
        {
            using (JsonDocument json = Parse(body))
            {
                JsonElement root = json.RootElement;
                Document d = ActiveDocument();
                if (!root.TryGetProperty("operations", out JsonElement operations) ||
                    operations.ValueKind != JsonValueKind.Array)
                    throw new BridgeException("invalid_batch", "operations must be an array");
                if (operations.GetArrayLength() == 0)
                    throw new BridgeException("invalid_batch", "operations must not be empty");
                if (operations.GetArrayLength() > 2000)
                    throw new BridgeException("invalid_batch", "operations exceeds 2000 items");

                bool dryRun = GetBoolean(root, "dry_run", false);
                bool requestedAtomic = GetBoolean(root, "atomic", true);
                string key = GetString(root, "idempotency_key");
                string docId = DocumentId(d);
                string expectedDocument = GetString(root, "expected_document_id");
                if (!string.IsNullOrWhiteSpace(expectedDocument) &&
                    !expectedDocument.Equals(docId, StringComparison.Ordinal))
                {
                    throw new BridgeException(
                        "document_mismatch",
                        "Refusing write: expected document " + expectedDocument +
                        " but active document is " + docId);
                }
                string fingerprint = GetString(root, "idempotency_fingerprint");
                if (string.IsNullOrWhiteSpace(fingerprint))
                    fingerprint = Sha256(operations.GetRawText());
                string appliedFingerprint = string.IsNullOrWhiteSpace(key)
                    ? null
                    : AppliedFingerprint(docId, key);
                if (appliedFingerprint != null)
                {
                    if (!appliedFingerprint.Equals(fingerprint, StringComparison.OrdinalIgnoreCase))
                        throw new BridgeException(
                            "idempotency_conflict",
                            "The idempotency key was already used for a different batch: " + key);
                    return Serialize(new
                    {
                        ok = true,
                        status = "idempotent_replay",
                        skipped = true,
                        idempotency_key = key,
                        document_id = docId,
                        revision = Revision(d),
                        items = Array.Empty<object>()
                    });
                }
                CheckExpected(d, root);

                JsonElement[] opArray = operations.EnumerateArray().ToArray();
                foreach (JsonElement op in opArray) ValidateOperation(op);
                if (dryRun)
                {
                    return Serialize(new
                    {
                        ok = true,
                        status = "dry_run",
                        dry_run = true,
                        atomic = true,
                        requested_atomic = requestedAtomic,
                        operation_count = opArray.Length,
                        types = opArray.Select(op => RequireString(op, "type")).ToArray(),
                        document_id = docId,
                        revision = Revision(d)
                    });
                }

                BatchResult result = ApplyOperations(d, opArray, true);
                if (!string.IsNullOrWhiteSpace(key)) MarkApplied(docId, key, fingerprint);
                return Serialize(new
                {
                    ok = true,
                    status = "committed",
                    dry_run = false,
                    atomic = true,
                    requested_atomic = requestedAtomic,
                    idempotency_key = key,
                    operation_count = result.Items.Count,
                    items = result.Items.Select(x => new
                    {
                        op_id = x.OpId,
                        type = x.Type,
                        handle = x.Handle
                    }).ToArray(),
                    document_id = docId,
                    revision = Revision(d)
                });
            }
        }

        private BatchResult ApplyOperations(Document d, IEnumerable<JsonElement> operations, bool atomic)
        {
            Database db = d.Database;
            var result = new BatchResult();
            using (DocumentLock docLock = d.LockDocument())
            using (Transaction tr = db.TransactionManager.StartTransaction())
            {
                var bt = tr.GetObject(db.BlockTableId, OpenMode.ForRead) as BlockTable;
                var model = tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite) as BlockTableRecord;
                foreach (JsonElement op in operations)
                {
                    ValidateOperation(op);
                    Entity entity = BuildEntity(op, db, tr);
                    ApplyLayer(entity, op, db, tr);
                    ObjectId id = model.AppendEntity(entity);
                    tr.AddNewlyCreatedDBObject(entity, true);
                    result.Items.Add(new BatchItem
                    {
                        OpId = GetString(op, "id"),
                        Type = RequireString(op, "type").ToLowerInvariant(),
                        Handle = entity.Handle.ToString()
                    });
                }
                tr.Commit();
            }
            return result;
        }

        private static void ValidateOperation(JsonElement op)
        {
            string type = RequireString(op, "type").ToLowerInvariant();
            switch (type)
            {
                case "line":
                    RequirePointArray(op, "p", 4);
                    break;
                case "rect":
                    RequirePointArray(op, "p", 4);
                    if (op.GetProperty("p")[2].GetDouble() == 0 || op.GetProperty("p")[3].GetDouble() == 0)
                        throw new BridgeException("invalid_geometry", "Rectangle width and height must be non-zero");
                    break;
                case "circle":
                    RequirePointArray(op, "p", 3);
                    if (op.GetProperty("p")[2].GetDouble() <= 0)
                        throw new BridgeException("invalid_geometry", "Circle radius must be positive");
                    break;
                case "arc":
                    RequirePointArray(op, "p", 5);
                    if (op.GetProperty("p")[2].GetDouble() <= 0)
                        throw new BridgeException("invalid_geometry", "Arc radius must be positive");
                    break;
                case "pline":
                case "polyline":
                    if (!op.TryGetProperty("pts", out JsonElement pts) ||
                        pts.ValueKind != JsonValueKind.Array || pts.GetArrayLength() < 2)
                        throw new BridgeException("invalid_geometry", "Polyline pts must contain at least two [x,y] points");
                    foreach (JsonElement point in pts.EnumerateArray())
                        if (point.ValueKind != JsonValueKind.Array || point.GetArrayLength() < 2)
                            throw new BridgeException("invalid_geometry", "Each polyline point must be [x,y]");
                    break;
                case "text":
                    RequirePointArray(op, "p", 2);
                    RequireString(op, "text");
                    break;
                case "mtext":
                    RequirePointArray(op, "p", 2);
                    RequireString(op, "text");
                    break;
                case "dim":
                case "dimension":
                    RequirePointArray(op, "p", 6);
                    break;
                default:
                    throw new BridgeException("unknown_draw_type", "Unsupported draw type: " + type);
            }
        }

        private static Entity BuildEntity(JsonElement op, Database db, Transaction tr)
        {
            string type = RequireString(op, "type").ToLowerInvariant();
            JsonElement p;
            switch (type)
            {
                case "line":
                    p = op.GetProperty("p");
                    return new Line(P3(p[0], p[1]), P3(p[2], p[3]));
                case "rect":
                    p = op.GetProperty("p");
                    double x = p[0].GetDouble(), y = p[1].GetDouble();
                    double width = p[2].GetDouble(), height = p[3].GetDouble();
                    var rect = new Polyline();
                    rect.AddVertexAt(0, new Point2d(x, y), 0, 0, 0);
                    rect.AddVertexAt(1, new Point2d(x + width, y), 0, 0, 0);
                    rect.AddVertexAt(2, new Point2d(x + width, y + height), 0, 0, 0);
                    rect.AddVertexAt(3, new Point2d(x, y + height), 0, 0, 0);
                    rect.Closed = true;
                    return rect;
                case "circle":
                    p = op.GetProperty("p");
                    return new Circle(P3(p[0], p[1]), Vector3d.ZAxis, p[2].GetDouble());
                case "arc":
                    p = op.GetProperty("p");
                    return new Arc(
                        P3(p[0], p[1]),
                        Vector3d.ZAxis,
                        p[2].GetDouble(),
                        Degrees(p[3].GetDouble()),
                        Degrees(p[4].GetDouble()));
                case "pline":
                case "polyline":
                    var polyline = new Polyline();
                    int index = 0;
                    foreach (JsonElement point in op.GetProperty("pts").EnumerateArray())
                    {
                        polyline.AddVertexAt(
                            index++,
                            new Point2d(point[0].GetDouble(), point[1].GetDouble()),
                            0,
                            0,
                            0);
                    }
                    polyline.Closed = GetBoolean(op, "closed", false);
                    return polyline;
                case "text":
                    p = op.GetProperty("p");
                    var text = new DBText
                    {
                        Position = P3(p[0], p[1]),
                        TextString = RequireString(op, "text"),
                        Height = GetDouble(op, "height", p.GetArrayLength() > 2 ? p[2].GetDouble() : 3.5),
                        Rotation = Degrees(GetDouble(op, "rotation", p.GetArrayLength() > 3 ? p[3].GetDouble() : 0))
                    };
                    ApplyTextStyle(text, op, db, tr);
                    return text;
                case "mtext":
                    p = op.GetProperty("p");
                    var mtext = new MText
                    {
                        Location = P3(p[0], p[1]),
                        Contents = RequireString(op, "text"),
                        TextHeight = GetDouble(op, "height", 3.5),
                        Width = GetDouble(op, "width", 100.0)
                    };
                    ApplyTextStyle(mtext, op, db, tr);
                    return mtext;
                case "dim":
                case "dimension":
                    p = op.GetProperty("p");
                    var dim = new AlignedDimension(
                        P3(p[0], p[1]),
                        P3(p[2], p[3]),
                        P3(p[4], p[5]),
                        GetString(op, "text") ?? "",
                        ResolveDimStyle(op, db, tr));
                    return dim;
                default:
                    throw new BridgeException("unknown_draw_type", "Unsupported draw type: " + type);
            }
        }

        private static void ApplyTextStyle(DBText text, JsonElement op, Database db, Transaction tr)
        {
            string style = GetString(op, "style");
            if (string.IsNullOrWhiteSpace(style)) return;
            var table = tr.GetObject(db.TextStyleTableId, OpenMode.ForRead) as TextStyleTable;
            if (!table.Has(style)) throw new BridgeException("text_style_not_found", "Text style not found: " + style);
            text.TextStyleId = table[style];
        }

        private static void ApplyTextStyle(MText text, JsonElement op, Database db, Transaction tr)
        {
            string style = GetString(op, "style");
            if (string.IsNullOrWhiteSpace(style)) return;
            var table = tr.GetObject(db.TextStyleTableId, OpenMode.ForRead) as TextStyleTable;
            if (!table.Has(style)) throw new BridgeException("text_style_not_found", "Text style not found: " + style);
            text.TextStyleId = table[style];
        }

        private static ObjectId ResolveDimStyle(JsonElement op, Database db, Transaction tr)
        {
            string style = GetString(op, "dimstyle");
            if (string.IsNullOrWhiteSpace(style)) return db.Dimstyle;
            var table = tr.GetObject(db.DimStyleTableId, OpenMode.ForRead) as DimStyleTable;
            if (!table.Has(style)) throw new BridgeException("dim_style_not_found", "Dimension style not found: " + style);
            return table[style];
        }

        private static void ApplyLayer(Entity entity, JsonElement op, Database db, Transaction tr)
        {
            string layer = GetString(op, "layer");
            if (string.IsNullOrWhiteSpace(layer)) return;
            var table = tr.GetObject(db.LayerTableId, OpenMode.ForRead) as LayerTable;
            if (!table.Has(layer)) throw new BridgeException("layer_not_found", "Layer not found: " + layer);
            entity.LayerId = table[layer];
        }

        private string Edit(string body)
        {
            using (JsonDocument json = Parse(body))
            {
                JsonElement root = json.RootElement;
                Document d = ActiveDocument();
                CheckExpected(d, root);
                string action = RequireString(root, "action").ToLowerInvariant();
                string[] handles = ReadStringArray(root, "handles");
                if (action != "offset" && handles.Length == 0)
                    throw new BridgeException("invalid_handles", "handles must not be empty");
                Database db = d.Database;
                var newHandles = new List<string>();
                int affected = 0;
                using (DocumentLock docLock = d.LockDocument())
                using (Transaction tr = db.TransactionManager.StartTransaction())
                {
                    var bt = tr.GetObject(db.BlockTableId, OpenMode.ForRead) as BlockTable;
                    var model = tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForWrite) as BlockTableRecord;
                    if (action == "offset")
                    {
                        string handle = GetString(root, "handle") ?? handles.FirstOrDefault();
                        if (string.IsNullOrWhiteSpace(handle))
                            throw new BridgeException("invalid_handles", "offset requires handle");
                        Entity source = OpenEntityByHandle(db, tr, handle, OpenMode.ForRead);
                        double distance = GetDouble(root, "distance", 0);
                        if (Math.Abs(distance) < 1e-12)
                            throw new BridgeException("invalid_distance", "offset distance must be non-zero");
                        DBObjectCollection selected = SelectOffsetCurves(source, root, distance);
                        foreach (DBObject obj in selected)
                        {
                            if (!(obj is Entity created)) { obj.Dispose(); continue; }
                            model.AppendEntity(created);
                            tr.AddNewlyCreatedDBObject(created, true);
                            newHandles.Add(created.Handle.ToString());
                            affected++;
                        }
                    }
                    else
                    {
                        Matrix3d transform = Matrix3d.Identity;
                        if (action == "move")
                            transform = Matrix3d.Displacement(new Vector3d(
                                GetDouble(root, "dx", 0), GetDouble(root, "dy", 0), 0));
                        else if (action == "rotate")
                            transform = Matrix3d.Rotation(
                                Degrees(GetDouble(root, "angle", 0)),
                                Vector3d.ZAxis,
                                new Point3d(GetDouble(root, "bx", 0), GetDouble(root, "by", 0), 0));
                        else if (action == "scale")
                            transform = Matrix3d.Scaling(
                                GetDouble(root, "factor", 1),
                                new Point3d(GetDouble(root, "bx", 0), GetDouble(root, "by", 0), 0));
                        else if (action == "mirror")
                            transform = Matrix3d.Mirroring(new Line3d(
                                new Point3d(GetDouble(root, "x1", 0), GetDouble(root, "y1", 0), 0),
                                new Point3d(GetDouble(root, "x2", 0), GetDouble(root, "y2", 0), 0)));

                        int copyCount = Math.Max(1, GetInt(root, "count", 1));
                        foreach (string handle in handles)
                        {
                            Entity entity = OpenEntityByHandle(
                                db, tr, handle,
                                action == "copy" ? OpenMode.ForRead : OpenMode.ForWrite);
                            if (action == "erase")
                            {
                                entity.Erase();
                                affected++;
                            }
                            else if (action == "copy")
                            {
                                double dx = GetDouble(root, "dx", 0);
                                double dy = GetDouble(root, "dy", 0);
                                for (int i = 1; i <= copyCount; i++)
                                {
                                    var clone = entity.Clone() as Entity;
                                    clone.TransformBy(Matrix3d.Displacement(new Vector3d(dx * i, dy * i, 0)));
                                    model.AppendEntity(clone);
                                    tr.AddNewlyCreatedDBObject(clone, true);
                                    newHandles.Add(clone.Handle.ToString());
                                    affected++;
                                }
                            }
                            else if (action == "move" || action == "rotate" ||
                                     action == "scale" || action == "mirror")
                            {
                                entity.TransformBy(transform);
                                affected++;
                            }
                            else
                                throw new BridgeException("unknown_edit_action", "Unsupported edit action: " + action);
                        }
                    }
                    tr.Commit();
                }
                return Serialize(new
                {
                    ok = true,
                    action = action,
                    affected = affected,
                    handles = handles,
                    new_handles = newHandles,
                    document_id = DocumentId(d),
                    revision = Revision(d)
                });
            }
        }

        private static DBObjectCollection SelectOffsetCurves(Entity source, JsonElement root, double distance)
        {
            var curve = source as Curve;
            if (curve == null)
                throw new BridgeException("offset_not_supported", "Offset requires a curve entity");
            if (!root.TryGetProperty("side_point", out JsonElement point) ||
                point.ValueKind != JsonValueKind.Array || point.GetArrayLength() < 2)
                return curve.GetOffsetCurves(distance);

            Point3d side = new Point3d(point[0].GetDouble(), point[1].GetDouble(), 0);
            double magnitude = Math.Abs(distance);
            DBObjectCollection positive = curve.GetOffsetCurves(magnitude);
            DBObjectCollection negative = curve.GetOffsetCurves(-magnitude);
            double positiveDistance = CollectionDistance(positive, side);
            double negativeDistance = CollectionDistance(negative, side);
            DBObjectCollection keep = positiveDistance <= negativeDistance ? positive : negative;
            DBObjectCollection discard = keep == positive ? negative : positive;
            foreach (DBObject obj in discard) obj.Dispose();
            return keep;
        }

        private static double CollectionDistance(DBObjectCollection objects, Point3d point)
        {
            double best = double.MaxValue;
            foreach (DBObject obj in objects)
            {
                if (!(obj is Entity entity)) continue;
                try
                {
                    Extents3d ext = entity.GeometricExtents;
                    Point3d center = new Point3d(
                        (ext.MinPoint.X + ext.MaxPoint.X) / 2,
                        (ext.MinPoint.Y + ext.MaxPoint.Y) / 2,
                        (ext.MinPoint.Z + ext.MaxPoint.Z) / 2);
                    best = Math.Min(best, center.DistanceTo(point));
                }
                catch { }
            }
            return best;
        }

        private string QueryEntities(string body)
        {
            using (JsonDocument json = Parse(body))
            {
                JsonElement root = json.RootElement;
                Document d = ActiveDocument();
                if (d == null) throw new BridgeException("no_document", "No active AutoCAD document");
                string filter = (GetString(root, "object_filter") ?? "").ToLowerInvariant();
                string layerFilter = GetString(root, "layer");
                int limit = Math.Max(1, Math.Min(5000, GetInt(root, "limit", 200)));
                var requestedHandles = new HashSet<string>(
                    ReadStringArray(root, "handles"),
                    StringComparer.OrdinalIgnoreCase);
                var items = new List<Dictionary<string, object>>();
                var counts = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
                using (DocumentLock docLock = d.LockDocument())
                using (Transaction tr = d.Database.TransactionManager.StartOpenCloseTransaction())
                {
                    var bt = tr.GetObject(d.Database.BlockTableId, OpenMode.ForRead) as BlockTable;
                    var model = tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead) as BlockTableRecord;
                    foreach (ObjectId id in model)
                    {
                        if (items.Count >= limit) break;
                        var entity = tr.GetObject(id, OpenMode.ForRead, false) as Entity;
                        if (entity == null) continue;
                        string handle = entity.Handle.ToString();
                        string dxf = entity.GetRXClass().DxfName ?? entity.GetType().Name;
                        if (requestedHandles.Count > 0 && !requestedHandles.Contains(handle)) continue;
                        if (!string.IsNullOrWhiteSpace(filter) &&
                            dxf.ToLowerInvariant().IndexOf(filter, StringComparison.Ordinal) < 0 &&
                            entity.GetType().Name.ToLowerInvariant().IndexOf(filter, StringComparison.Ordinal) < 0)
                            continue;
                        if (!string.IsNullOrWhiteSpace(layerFilter) &&
                            !entity.Layer.Equals(layerFilter, StringComparison.OrdinalIgnoreCase))
                            continue;
                        counts[dxf] = counts.TryGetValue(dxf, out int count) ? count + 1 : 1;
                        items.Add(EntityInfo(entity, tr));
                    }
                }
                return Serialize(new
                {
                    ok = true,
                    document_id = DocumentId(d),
                    revision = Revision(d),
                    count = items.Count,
                    counts = counts,
                    items = items
                });
            }
        }

        private static Dictionary<string, object> EntityInfo(Entity entity, Transaction tr)
        {
            var item = new Dictionary<string, object>
            {
                ["handle"] = entity.Handle.ToString(),
                ["type"] = entity.GetRXClass().DxfName ?? entity.GetType().Name,
                ["class"] = entity.GetType().Name,
                ["layer"] = entity.Layer,
                ["color_index"] = entity.ColorIndex,
                ["linetype"] = entity.Linetype
            };
            try
            {
                Extents3d ext = entity.GeometricExtents;
                item["bounds"] = new[]
                {
                    ext.MinPoint.X, ext.MinPoint.Y, ext.MinPoint.Z,
                    ext.MaxPoint.X, ext.MaxPoint.Y, ext.MaxPoint.Z
                };
            }
            catch { item["bounds"] = null; }

            if (entity is Line line)
            {
                item["start"] = Point(line.StartPoint);
                item["end"] = Point(line.EndPoint);
                item["length"] = line.Length;
            }
            else if (entity is Circle circle)
            {
                item["center"] = Point(circle.Center);
                item["radius"] = circle.Radius;
            }
            else if (entity is Arc arc)
            {
                item["center"] = Point(arc.Center);
                item["radius"] = arc.Radius;
                item["start_angle_deg"] = arc.StartAngle * 180.0 / Math.PI;
                item["end_angle_deg"] = arc.EndAngle * 180.0 / Math.PI;
            }
            else if (entity is Polyline polyline)
            {
                var points = new List<double[]>();
                for (int i = 0; i < polyline.NumberOfVertices; i++)
                {
                    Point2d p = polyline.GetPoint2dAt(i);
                    points.Add(new[] { p.X, p.Y });
                }
                item["points"] = points;
                item["closed"] = polyline.Closed;
                try { item["length"] = polyline.Length; } catch { }
            }
            else if (entity is DBText dbText)
            {
                item["position"] = Point(dbText.Position);
                item["text"] = dbText.TextString;
                item["height"] = dbText.Height;
                item["rotation_deg"] = dbText.Rotation * 180.0 / Math.PI;
                var style = tr.GetObject(dbText.TextStyleId, OpenMode.ForRead) as TextStyleTableRecord;
                item["style"] = style != null ? style.Name : "";
            }
            else if (entity is MText mtext)
            {
                item["position"] = Point(mtext.Location);
                item["text"] = mtext.Contents;
                item["height"] = mtext.TextHeight;
                item["width"] = mtext.Width;
            }
            else if (entity is Dimension dimension)
            {
                item["measurement"] = dimension.Measurement;
                item["text"] = dimension.DimensionText;
            }
            return item;
        }

        private string SelectEntities(string body)
        {
            using (JsonDocument json = Parse(body))
            {
                JsonElement root = json.RootElement;
                Document d = ActiveDocument();
                if (d == null) throw new BridgeException("no_document", "No active AutoCAD document");
                double x1 = RequireDouble(root, "x1"), y1 = RequireDouble(root, "y1");
                double x2 = RequireDouble(root, "x2"), y2 = RequireDouble(root, "y2");
                double minX = Math.Min(x1, x2), maxX = Math.Max(x1, x2);
                double minY = Math.Min(y1, y2), maxY = Math.Max(y1, y2);
                bool crossing = GetBoolean(root, "crossing", false);
                var handles = new List<string>();
                using (DocumentLock docLock = d.LockDocument())
                using (Transaction tr = d.Database.TransactionManager.StartOpenCloseTransaction())
                {
                    var bt = tr.GetObject(d.Database.BlockTableId, OpenMode.ForRead) as BlockTable;
                    var model = tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead) as BlockTableRecord;
                    foreach (ObjectId id in model)
                    {
                        var entity = tr.GetObject(id, OpenMode.ForRead, false) as Entity;
                        if (entity == null) continue;
                        try
                        {
                            Extents3d ext = entity.GeometricExtents;
                            bool inside = ext.MinPoint.X >= minX && ext.MaxPoint.X <= maxX &&
                                          ext.MinPoint.Y >= minY && ext.MaxPoint.Y <= maxY;
                            bool intersects = ext.MaxPoint.X >= minX && ext.MinPoint.X <= maxX &&
                                              ext.MaxPoint.Y >= minY && ext.MinPoint.Y <= maxY;
                            if (inside || (crossing && intersects)) handles.Add(entity.Handle.ToString());
                        }
                        catch { }
                    }
                }
                return Serialize(new
                {
                    ok = true,
                    mode = crossing ? "crossing" : "window",
                    count = handles.Count,
                    handles = handles,
                    document_id = DocumentId(d),
                    revision = Revision(d)
                });
            }
        }

        private string ValidateDrawing(string body)
        {
            using (JsonDocument json = Parse(body))
            {
                JsonElement root = json.RootElement;
                Document d = ActiveDocument();
                if (d == null) throw new BridgeException("no_document", "No active AutoCAD document");
                double tolerance = Math.Max(1e-9, GetDouble(root, "tolerance", 0.01));
                string[] requiredLayers = ReadStringArray(root, "required_layers");
                bool requireClosed = GetBoolean(root, "require_closed_polylines", false);
                var issues = new List<Dictionary<string, object>>();
                var byType = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
                var byLayer = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
                var lineKeys = new Dictionary<string, string>(StringComparer.Ordinal);
                int entityCount = 0;
                using (DocumentLock docLock = d.LockDocument())
                using (Transaction tr = d.Database.TransactionManager.StartOpenCloseTransaction())
                {
                    var layerTable = tr.GetObject(d.Database.LayerTableId, OpenMode.ForRead) as LayerTable;
                    foreach (string layer in requiredLayers)
                    {
                        if (!layerTable.Has(layer))
                            issues.Add(Issue("error", "missing_layer", "Required layer is missing: " + layer, null));
                    }
                    var bt = tr.GetObject(d.Database.BlockTableId, OpenMode.ForRead) as BlockTable;
                    var model = tr.GetObject(bt[BlockTableRecord.ModelSpace], OpenMode.ForRead) as BlockTableRecord;
                    foreach (ObjectId id in model)
                    {
                        var entity = tr.GetObject(id, OpenMode.ForRead, false) as Entity;
                        if (entity == null) continue;
                        entityCount++;
                        string type = entity.GetRXClass().DxfName ?? entity.GetType().Name;
                        byType[type] = byType.TryGetValue(type, out int tc) ? tc + 1 : 1;
                        byLayer[entity.Layer] = byLayer.TryGetValue(entity.Layer, out int lc) ? lc + 1 : 1;
                        if (entity is Line line)
                        {
                            if (line.Length <= tolerance)
                                issues.Add(Issue("error", "zero_length", "Line length is at or below tolerance", entity.Handle.ToString()));
                            string key = NormalizedLineKey(line, tolerance);
                            if (lineKeys.TryGetValue(key, out string first))
                                issues.Add(Issue("warning", "duplicate_line", "Duplicate line overlaps handle " + first, entity.Handle.ToString()));
                            else lineKeys[key] = entity.Handle.ToString();
                            if (Math.Abs(line.StartPoint.Z) > tolerance || Math.Abs(line.EndPoint.Z) > tolerance)
                                issues.Add(Issue("warning", "off_plane", "Line has non-zero Z", entity.Handle.ToString()));
                        }
                        else if (entity is Polyline polyline)
                        {
                            if (polyline.NumberOfVertices < 2 || polyline.Length <= tolerance)
                                issues.Add(Issue("error", "degenerate_polyline", "Polyline is degenerate", entity.Handle.ToString()));
                            if (requireClosed && !polyline.Closed)
                                issues.Add(Issue("warning", "open_polyline", "Polyline is open", entity.Handle.ToString()));
                            if (Math.Abs(polyline.Elevation) > tolerance)
                                issues.Add(Issue("warning", "off_plane", "Polyline has non-zero elevation", entity.Handle.ToString()));
                        }
                        else if (entity is Circle circle && circle.Radius <= tolerance)
                            issues.Add(Issue("error", "small_radius", "Circle radius is at or below tolerance", entity.Handle.ToString()));
                    }
                }
                if (entityCount == 0)
                    issues.Add(Issue("warning", "empty_modelspace", "Model space contains no entities", null));
                int penalty = issues.Sum(issue =>
                    (string)issue["severity"] == "error" ? 12 : 4);
                return Serialize(new
                {
                    ok = issues.All(issue => (string)issue["severity"] != "error"),
                    score = Math.Max(0, 100 - penalty),
                    document_id = DocumentId(d),
                    revision = Revision(d),
                    tolerance = tolerance,
                    entity_count = entityCount,
                    counts_by_type = byType,
                    counts_by_layer = byLayer,
                    issue_count = issues.Count,
                    issues = issues
                });
            }
        }

        private string Zoom(string body)
        {
            using (JsonDocument json = Parse(body))
            {
                JsonElement root = json.RootElement;
                Document d = ActiveDocument();
                if (d == null) throw new BridgeException("no_document", "No active AutoCAD document");
                Extents3d extents;
                string handle = GetString(root, "handle");
                using (DocumentLock docLock = d.LockDocument())
                using (Transaction tr = d.Database.TransactionManager.StartOpenCloseTransaction())
                {
                    if (!string.IsNullOrWhiteSpace(handle))
                    {
                        Entity entity = OpenEntityByHandle(d.Database, tr, handle, OpenMode.ForRead);
                        extents = entity.GeometricExtents;
                    }
                    else
                    {
                        d.Database.UpdateExt(true);
                        extents = new Extents3d(d.Database.Extmin, d.Database.Extmax);
                    }
                }
                double margin = Math.Max(1.0, GetDouble(root, "margin", 1.10));
                double width = Math.Max(1e-6, extents.MaxPoint.X - extents.MinPoint.X) * margin;
                double height = Math.Max(1e-6, extents.MaxPoint.Y - extents.MinPoint.Y) * margin;
                Editor editor = d.Editor;
                using (ViewTableRecord view = editor.GetCurrentView())
                {
                    double aspect = view.Width / Math.Max(view.Height, 1e-9);
                    if (width / height > aspect) height = width / aspect;
                    else width = height * aspect;
                    view.CenterPoint = new Point2d(
                        (extents.MinPoint.X + extents.MaxPoint.X) / 2,
                        (extents.MinPoint.Y + extents.MaxPoint.Y) / 2);
                    view.Width = width;
                    view.Height = height;
                    editor.SetCurrentView(view);
                }
                editor.Regen();
                return Serialize(new
                {
                    ok = true,
                    handle = handle,
                    bounds = new[]
                    {
                        extents.MinPoint.X, extents.MinPoint.Y,
                        extents.MaxPoint.X, extents.MaxPoint.Y
                    },
                    document_id = DocumentId(d),
                    revision = Revision(d)
                });
            }
        }

        private string SaveAs(string body)
        {
            using (JsonDocument json = Parse(body))
            {
                JsonElement root = json.RootElement;
                Document d = ActiveDocument();
                CheckExpected(d, root);
                string path = Path.GetFullPath(RequireString(root, "path"));
                string format = (GetString(root, "fmt") ?? "dwg").ToLowerInvariant();
                bool overwrite = GetBoolean(root, "overwrite", false);
                string directory = Path.GetDirectoryName(path);
                if (string.IsNullOrWhiteSpace(directory) || !Directory.Exists(directory))
                    throw new BridgeException("directory_not_found", "Output directory does not exist: " + directory);
                if (File.Exists(path) && !overwrite)
                    throw new BridgeException("file_exists", "Output exists; pass overwrite=true to replace it: " + path);

                bool dxf = format.StartsWith("dxf", StringComparison.Ordinal);
                string extension = Path.GetExtension(path).ToLowerInvariant();
                if (dxf && extension != ".dxf")
                    throw new BridgeException("format_extension_mismatch", "DXF output path must end in .dxf");
                if (!dxf && extension != ".dwg")
                    throw new BridgeException("format_extension_mismatch", "DWG output path must end in .dwg");

                DwgVersion version = VersionForFormat(format);
                using (DocumentLock docLock = d.LockDocument())
                {
                    if (dxf) d.Database.DxfOut(path, 16, version);
                    else d.Database.SaveAs(path, version);
                }
                return Serialize(new
                {
                    ok = true,
                    path = path,
                    format = format,
                    dwg_version = version.ToString(),
                    document_id = DocumentId(d),
                    revision = Revision(d)
                });
            }
        }

        private string Save(string body)
        {
            using (JsonDocument json = Parse(body))
            {
                JsonElement root = json.RootElement;
                Document d = ActiveDocument();
                CheckExpected(d, root);
                string path = d.Database.Filename;
                if (string.IsNullOrWhiteSpace(path))
                    throw new BridgeException("unsaved_document", "Current drawing has no file path; use cad_save_as");
                using (DocumentLock docLock = d.LockDocument())
                    d.Database.SaveAs(path, DwgVersion.Current);
                return Serialize(new
                {
                    ok = true,
                    path = path,
                    document_id = DocumentId(d),
                    revision = Revision(d)
                });
            }
        }

        private string QueueCommand(string body)
        {
            using (JsonDocument json = Parse(body))
            {
                JsonElement root = json.RootElement;
                Document d = ActiveDocument();
                CheckExpected(d, root);
                string command = root.ValueKind == JsonValueKind.String
                    ? root.GetString()
                    : RequireString(root, "cmd");
                if (string.IsNullOrWhiteSpace(command))
                    throw new BridgeException("empty_command", "Command must not be empty");
                string firstToken = command.Trim().Split(new[] { ' ', '\t', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)[0];
                string jobId = Guid.NewGuid().ToString("N");
                var job = new CommandJob
                {
                    Id = jobId,
                    Command = command,
                    CommandName = firstToken.TrimStart('.', '_', '-').ToUpperInvariant(),
                    DocumentId = DocumentId(d),
                    Status = "pending",
                    CreatedUtc = DateTime.UtcNow
                };
                _jobs[jobId] = job;
                d.SendStringToExecute(command.TrimEnd() + "\n", true, false, true);
                return Serialize(JobObject(job, d));
            }
        }

        private string JobStatus(string body)
        {
            JsonElement root = ParseObject(body);
            string jobId = RequireString(root, "job_id");
            if (!_jobs.TryGetValue(jobId, out CommandJob job))
                return Error("job_not_found", "Unknown command job: " + jobId);
            Document d = ActiveDocument();
            return Serialize(JobObject(job, d));
        }

        private object JobObject(CommandJob job, Document d)
        {
            return new
            {
                ok = true,
                job_id = job.Id,
                status = job.Status,
                completed = job.Status == "completed",
                terminal = job.Status == "completed" || job.Status == "failed" || job.Status == "cancelled",
                command = job.Command,
                command_name = job.CommandName,
                document_id = job.DocumentId,
                created_utc = job.CreatedUtc.ToString("O", CultureInfo.InvariantCulture),
                updated_utc = job.UpdatedUtc == default(DateTime)
                    ? null
                    : job.UpdatedUtc.ToString("O", CultureInfo.InvariantCulture),
                error = job.Error,
                command_active = d != null ? SafeSystemVariableInt("CMDACTIVE") : 0,
                command_names = d != null ? SafeSystemVariableString("CMDNAMES") : ""
            };
        }

        private void UpdateCommandJob(Document d, string globalName, string status, string error)
        {
            string normalized = (globalName ?? "").TrimStart('.', '_', '-').ToUpperInvariant();
            CommandJob candidate = _jobs.Values
                .Where(job => job.DocumentId == DocumentId(d) &&
                              (job.Status == "pending" || job.Status == "running") &&
                              (string.IsNullOrWhiteSpace(normalized) ||
                               job.CommandName.IndexOf(normalized, StringComparison.OrdinalIgnoreCase) >= 0 ||
                               normalized.IndexOf(job.CommandName, StringComparison.OrdinalIgnoreCase) >= 0))
                .OrderBy(job => job.CreatedUtc)
                .FirstOrDefault();
            if (candidate == null) return;
            candidate.Status = status;
            candidate.Error = error;
            candidate.UpdatedUtc = DateTime.UtcNow;
        }

        private static DwgVersion VersionForFormat(string format)
        {
            switch (format)
            {
                case "dwg":
                case "dwg2018":
                case "dxf":
                case "dxf2018":
                    return DwgVersion.AC1032;
                case "dwg2013":
                case "dxf2013":
                    return DwgVersion.AC1027;
                case "dwg2010":
                case "dxf2010":
                    return DwgVersion.AC1024;
                case "dwg2007":
                case "dxf2007":
                    return DwgVersion.AC1021;
                case "dwg2004":
                case "dxf2004":
                    return DwgVersion.AC1800;
                case "dwg2000":
                case "dxf2000":
                    return DwgVersion.AC1015;
                case "dxfr12":
                    return DwgVersion.AC1009;
                default:
                    throw new BridgeException("unsupported_format", "Unsupported save format: " + format);
            }
        }

        private static Entity OpenEntityByHandle(Database db, Transaction tr, string handle, OpenMode mode)
        {
            if (!long.TryParse(handle, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out long value))
                throw new BridgeException("invalid_handle", "Invalid hexadecimal handle: " + handle);
            ObjectId id;
            try { id = db.GetObjectId(false, new Handle(value), 0); }
            catch { throw new BridgeException("handle_not_found", "Entity handle not found: " + handle); }
            var entity = tr.GetObject(id, mode, false) as Entity;
            if (entity == null) throw new BridgeException("handle_not_entity", "Handle is not an entity: " + handle);
            return entity;
        }

        private static string Sha256(string value)
        {
            using (SHA256 hash = SHA256.Create())
            {
                byte[] bytes = hash.ComputeHash(Encoding.UTF8.GetBytes(value ?? ""));
                return BitConverter.ToString(bytes).Replace("-", "");
            }
        }

        private string AppliedFingerprint(string documentId, string key)
        {
            lock (_idempotency)
            {
                if (_idempotency.TryGetValue(documentId, out var keys) &&
                    keys.TryGetValue(key, out string fingerprint))
                    return fingerprint;
                return null;
            }
        }

        private void MarkApplied(string documentId, string key, string fingerprint)
        {
            lock (_idempotency)
            {
                if (!_idempotency.TryGetValue(documentId, out var keys))
                {
                    keys = new Dictionary<string, string>(StringComparer.Ordinal);
                    _idempotency[documentId] = keys;
                }
                keys[key] = fingerprint;
            }
        }

        private string CurrentLayerName(Document d)
        {
            using (Transaction tr = d.Database.TransactionManager.StartOpenCloseTransaction())
            {
                var layer = tr.GetObject(d.Database.Clayer, OpenMode.ForRead) as LayerTableRecord;
                return layer != null ? layer.Name : "";
            }
        }

        private Dictionary<string, object> DetectTarch()
        {
            var names = new List<string>();
            try
            {
                foreach (ProcessModule module in Process.GetCurrentProcess().Modules)
                {
                    string name = module.ModuleName ?? "";
                    if (name.IndexOf("tch", StringComparison.OrdinalIgnoreCase) >= 0 ||
                        name.IndexOf("tarch", StringComparison.OrdinalIgnoreCase) >= 0)
                        names.Add(name);
                }
            }
            catch { }
            return new Dictionary<string, object>
            {
                ["detected"] = names.Count > 0,
                ["modules"] = names.Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(x => x).ToArray()
            };
        }

        private void WriteDiscovery(string status, string error)
        {
            try
            {
                File.WriteAllText(
                    DiscoveryPath,
                    Serialize(new
                    {
                        status = status,
                        error = error,
                        protocol_version = ProtocolVersion,
                        plugin_version = PluginVersion,
                        process_id = _processId,
                        instance_id = _instanceId,
                        host = "127.0.0.1",
                        port = _port,
                        updated_utc = DateTime.UtcNow.ToString("O", CultureInfo.InvariantCulture)
                    }),
                    new UTF8Encoding(false));
            }
            catch { }
        }

        private static int SafeSystemVariableInt(string name)
        {
            try { return Convert.ToInt32(AcApplication.GetSystemVariable(name), CultureInfo.InvariantCulture); }
            catch { return 0; }
        }

        private static string SafeSystemVariableString(string name)
        {
            try { return Convert.ToString(AcApplication.GetSystemVariable(name), CultureInfo.InvariantCulture) ?? ""; }
            catch { return ""; }
        }

        private static JsonDocument Parse(string body)
        {
            if (string.IsNullOrWhiteSpace(body)) body = "{}";
            return JsonDocument.Parse(body);
        }

        private static JsonElement ParseObject(string body)
        {
            using (JsonDocument json = Parse(body))
                return json.RootElement.Clone();
        }

        private static string GetString(JsonElement root, string name)
        {
            if (root.ValueKind != JsonValueKind.Object ||
                !root.TryGetProperty(name, out JsonElement value) ||
                value.ValueKind == JsonValueKind.Null)
                return null;
            return value.ValueKind == JsonValueKind.String ? value.GetString() : value.ToString();
        }

        private static string RequireString(JsonElement root, string name)
        {
            string value = GetString(root, name);
            if (string.IsNullOrWhiteSpace(value))
                throw new BridgeException("missing_argument", "Missing required string: " + name);
            return value;
        }

        private static double GetDouble(JsonElement root, string name, double fallback)
        {
            if (root.ValueKind == JsonValueKind.Object &&
                root.TryGetProperty(name, out JsonElement value) &&
                value.ValueKind == JsonValueKind.Number)
                return value.GetDouble();
            return fallback;
        }

        private static double RequireDouble(JsonElement root, string name)
        {
            if (root.ValueKind == JsonValueKind.Object &&
                root.TryGetProperty(name, out JsonElement value) &&
                value.ValueKind == JsonValueKind.Number)
                return value.GetDouble();
            throw new BridgeException("missing_argument", "Missing required number: " + name);
        }

        private static int GetInt(JsonElement root, string name, int fallback)
        {
            if (root.ValueKind == JsonValueKind.Object &&
                root.TryGetProperty(name, out JsonElement value) &&
                value.ValueKind == JsonValueKind.Number &&
                value.TryGetInt32(out int number))
                return number;
            return fallback;
        }

        private static bool TryGetInt64(JsonElement root, string name, out long value)
        {
            value = 0;
            return root.ValueKind == JsonValueKind.Object &&
                   root.TryGetProperty(name, out JsonElement element) &&
                   element.ValueKind == JsonValueKind.Number &&
                   element.TryGetInt64(out value);
        }

        private static bool GetBoolean(JsonElement root, string name, bool fallback)
        {
            if (root.ValueKind != JsonValueKind.Object ||
                !root.TryGetProperty(name, out JsonElement value))
                return fallback;
            if (value.ValueKind == JsonValueKind.True) return true;
            if (value.ValueKind == JsonValueKind.False) return false;
            return fallback;
        }

        private static string[] ReadStringArray(JsonElement root, string name)
        {
            if (root.ValueKind != JsonValueKind.Object ||
                !root.TryGetProperty(name, out JsonElement values) ||
                values.ValueKind != JsonValueKind.Array)
                return Array.Empty<string>();
            return values.EnumerateArray()
                .Where(x => x.ValueKind == JsonValueKind.String)
                .Select(x => x.GetString())
                .Where(x => !string.IsNullOrWhiteSpace(x))
                .ToArray();
        }

        private static void RequirePointArray(JsonElement root, string name, int minimum)
        {
            if (!root.TryGetProperty(name, out JsonElement value) ||
                value.ValueKind != JsonValueKind.Array ||
                value.GetArrayLength() < minimum)
                throw new BridgeException(
                    "invalid_geometry",
                    name + " must be a numeric array with at least " + minimum + " values");
            foreach (JsonElement number in value.EnumerateArray())
                if (number.ValueKind != JsonValueKind.Number)
                    throw new BridgeException("invalid_geometry", name + " values must be numbers");
        }

        private static Point3d P3(JsonElement x, JsonElement y)
        {
            return new Point3d(x.GetDouble(), y.GetDouble(), 0);
        }

        private static double[] Point(Point3d p)
        {
            return new[] { p.X, p.Y, p.Z };
        }

        private static double Degrees(double degrees)
        {
            return Math.PI * degrees / 180.0;
        }

        private static Dictionary<string, object> Issue(
            string severity, string code, string message, string handle)
        {
            return new Dictionary<string, object>
            {
                ["severity"] = severity,
                ["code"] = code,
                ["message"] = message,
                ["handle"] = handle
            };
        }

        private static string NormalizedLineKey(Line line, double tolerance)
        {
            Func<Point3d, string> key = p =>
                Math.Round(p.X / tolerance).ToString(CultureInfo.InvariantCulture) + "," +
                Math.Round(p.Y / tolerance).ToString(CultureInfo.InvariantCulture) + "," +
                Math.Round(p.Z / tolerance).ToString(CultureInfo.InvariantCulture);
            string a = key(line.StartPoint), b = key(line.EndPoint);
            return string.CompareOrdinal(a, b) <= 0 ? a + "|" + b : b + "|" + a;
        }

        private static string Serialize(object value)
        {
            return JsonSerializer.Serialize(value);
        }

        private static string Error(string code, string message)
        {
            return Serialize(new { error = message, code = code, ok = false });
        }

        private static void Log(string message)
        {
            try
            {
                File.AppendAllText(
                    LogPath,
                    DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss ", CultureInfo.InvariantCulture) +
                    message + "\r\n");
            }
            catch { }
        }

        private sealed class HttpRequest
        {
            public string Method;
            public string Path;
            public string Body;
        }

        private sealed class CadWorkItem
        {
            public Func<string> Action;
            public readonly ManualResetEventSlim Done = new ManualResetEventSlim(false);
            public string Result;
        }

        private sealed class BridgeException : Exception
        {
            public string Code { get; private set; }
            public BridgeException(string code, string message) : base(message) { Code = code; }
        }

        private sealed class BatchResult
        {
            public readonly List<BatchItem> Items = new List<BatchItem>();
        }

        private sealed class BatchItem
        {
            public string OpId;
            public string Type;
            public string Handle;
        }

        private sealed class CommandJob
        {
            public string Id;
            public string Command;
            public string CommandName;
            public string DocumentId;
            public volatile string Status;
            public string Error;
            public DateTime CreatedUtc;
            public DateTime UpdatedUtc;
        }
    }
}
