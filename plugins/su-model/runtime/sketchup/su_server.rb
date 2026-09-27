# -*- coding: utf-8 -*-
# su_server.rb — SketchUp AI 自动建模服务
#
# 用法：在 SketchUp 的 Ruby 控制台执行（路径换成实际绝对路径，正斜杠）：
#   load "C:/path/to/repository/plugins/su-model/runtime/sketchup/su_server.rb"
#
# 控制台打开方式：
#   SketchUp 2021+   → 扩展程序(Extensions) → 开发者(Developer) → Ruby Console
#   SketchUp 2020 及更早 → 窗口(Window) → Ruby Console
#
# 启动后监听 http://127.0.0.1:45678，提供：
#   GET  /ping   → 健康检查 {"status":"ok"}
#   POST /eval   → body 为 Ruby 代码（TOPLEVEL_BINDING 执行），
#                  返回 {"status":"ok","result":...} 或 {"status":"error","error":...}
#
# 重复 load 报端口被占用时：先执行 Su.stop_server，再重新 load。
# 修改本文件后也需要 Su.stop_server + 重新 load 才生效。

require "socket"
require "json"
require "fileutils"
require "digest"

module Su
  PORT = 45678
  SERVER_VERSION = "2.0.0"
  API_SCHEMA_VERSION = "1.0"
  MAX_REQUEST_BYTES = 1_048_576
  ORIGIN = Geom::Point3d.new(0, 0, 0)
  ATTR_DICT = "codex_architecture"
  MAX_PLAN_OPERATIONS = 500

  # 各长度单位到模型单位（英寸）的换算系数；"model" 表示直接用模型当前单位
  UNIT_FACTOR = { "in" => 1.0, "ft" => 12.0, "mm" => 1.0 / 25.4, "cm" => 1.0 / 2.54, "m" => 1.0 / 0.0254 }
  VISUAL_RENDER_KEYS = %w[
    RenderMode Texture EdgeDisplayMode DrawSilhouettes DrawBackEdges DrawHidden
    DisplaySketchAxes DisplayDims DisplayText HideConstructionGeometry DisplayFog
    DrawGround DrawHorizon BackgroundColor GroundColor SkyColor
  ].freeze
  VISUAL_SHADOW_KEYS = %w[DisplayShadows UseSunForAllShading DisplayOnGroundPlane DisplayOnAllFaces].freeze

  class << self
    attr_accessor :server, :timer_id, :manual_operation_open

    def model
      m = Sketchup.active_model
      raise "没有打开模型！请先在 SketchUp 中新建或打开一个文件。" if m.nil?
      m
    end

    def entities
      model.entities
    end

    def model_unit
      opts = model.options["UnitsOptions"]
      return "in" unless opts["LengthFormat"] == Length::Decimal
      { Length::Inches => "in", Length::Feet => "ft", Length::Millimeter => "mm",
        Length::Centimeter => "cm", Length::Meter => "m" }[opts["LengthUnit"]] || "in"
    end

    def normalize_unit(unit, allow_nil = true)
      return nil if unit.nil? && allow_nil
      value = unit.to_s.downcase
      return model_unit if value == "model"
      return value if UNIT_FACTOR.key?(value)
      raise "未知单位: #{unit}（支持 in/ft/mm/cm/m/model）"
    end

    # SketchUp Ruby 内部长度始终是英寸。为兼容旧调用，unit=nil 表示“裸英寸”，
    # 不再把它误称为模型显示单位；需要模型显示单位时请显式传 :model。
    def conv(value, unit = nil)
      normalized = normalize_unit(unit)
      return value.to_f if normalized.nil?
      value.to_f * UNIT_FACTOR.fetch(normalized)
    end

    def from_inches(value, unit = nil)
      normalized = normalize_unit(unit)
      return [value.to_f, "in_raw"] if normalized.nil?
      [value.to_f / UNIT_FACTOR.fetch(normalized), normalized]
    end

    def pt(x, y, z, unit = nil)
      Geom::Point3d.new(conv(x, unit), conv(y, unit), conv(z, unit))
    end

    # 取或建材质并设颜色，返回材质对象；用法 face.material = Su.mat("墙", "#ff0000")
    def mat(name, hex_color, alpha = nil)
      m = model
      material = m.materials[name.to_s] || m.materials.add(name.to_s)
      hex = hex_color.to_s.sub(/\A#/, "")
      material.color = Sketchup::Color.new(hex[0, 2].to_i(16), hex[2, 2].to_i(16), hex[4, 2].to_i(16))
      material.alpha = alpha if alpha
      material
    end

    # 以 (x,y,z) 为起点建 w×d×h 的盒子（独立组），向上生长；h 为 0 时只建底面。返回组
    def box(name, x, y, z, w, d, h, unit = nil)
      raise "w/d 必须大于 0" if w <= 0 || d <= 0
      g = entities.add_group
      g.name = name.to_s
      pts = [pt(x, y, z, unit), pt(x + w, y, z, unit), pt(x + w, y + d, z, unit), pt(x, y + d, z, unit)]
      face = g.entities.add_face(pts)
      face.reverse! if face.normal.z < 0 # 保证正面朝上，pushpull 正值向上
      hh = conv(h, unit)
      face.pushpull(hh) unless hh == 0
      g
    end

    # 用点数组建面（自动闭合），返回 Face。方向由点序决定，可用 f.reverse! 翻转
    def face(pts, unit = nil)
      entities.add_face(pts.map { |p| pt(*p, unit) })
    end

    # 推拉：传 Face 推该面；传组/实例推其中所有面
    def pushpull(face_or_inst, distance, unit = nil)
      d = conv(distance, unit)
      case face_or_inst
      when Sketchup::Face then face_or_inst.pushpull(d)
      else face_or_inst.entities.grep(Sketchup::Face).each { |f| f.pushpull(d) }
      end
      true
    end

    def move(inst, dx, dy, dz, unit = nil)
      inst.transform!(Geom::Transformation.new([conv(dx, unit), conv(dy, unit), conv(dz, unit)]))
      inst
    end

    def rotate(inst, deg, axis = "z", center = nil)
      ax = case axis.to_s
           when "x" then Geom::Vector3d.new(1, 0, 0)
           when "y" then Geom::Vector3d.new(0, 1, 0)
           else          Geom::Vector3d.new(0, 0, 1)
           end
      inst.transform!(Geom::Transformation.rotation(center || ORIGIN, ax, deg.degrees))
      inst
    end

    def each_unique_edge(ents = model.entities, seen_definitions = {}, &block)
      ents.each do |entity|
        if entity.is_a?(Sketchup::Edge)
          block.call(entity)
        elsif entity.is_a?(Sketchup::Group)
          each_unique_edge(entity.entities, seen_definitions, &block)
        elsif entity.is_a?(Sketchup::ComponentInstance)
          definition = entity.definition
          key = definition.respond_to?(:persistent_id) ? definition.persistent_id : definition.object_id
          next if seen_definitions[key]
          seen_definitions[key] = true
          each_unique_edge(definition.entities, seen_definitions, &block)
        end
      end
    end

    # 临时隐藏边线并在 ensure 中恢复。用 abort_operation 保证截图不会把隐藏状态写进模型。
    def with_temporarily_hidden_edges
      raise "不能在手动事务中拍无边线截图；请先 Su.commit 或 Su.abort" if manual_operation_open
      m = model
      state = []
      operation_started = false
      begin
        m.start_operation("Codex temporary render", true)
        operation_started = true
        each_unique_edge do |edge|
          state << [edge, edge.hidden?]
          edge.hidden = true unless edge.hidden?
        end
        yield
      ensure
        if operation_started
          m.abort_operation
        else
          state.reverse_each { |edge, hidden| edge.hidden = hidden if edge.valid? }
        end
      end
    end

    # 兼容交互式调用。render_ready/capture_views 会自动临时隐藏并恢复，优先使用它们。
    def hide_edges
      raise "边线已处于手动隐藏状态" if @manual_edge_state
      @manual_edge_state = []
      each_unique_edge do |edge|
        @manual_edge_state << [edge, edge.hidden?]
        edge.hidden = true unless edge.hidden?
      end
      @manual_edge_state.length
    end

    def show_edges
      return 0 unless @manual_edge_state
      count = @manual_edge_state.length
      @manual_edge_state.reverse_each { |edge, hidden| edge.hidden = hidden if edge.valid? }
      @manual_edge_state = nil
      count
    end

    def camera_state(camera = model.active_view.camera)
      {
        "eye" => camera.eye.to_a,
        "target" => camera.target.to_a,
        "up" => camera.up.to_a,
        "perspective" => camera.perspective?,
        "fov" => camera.fov,
        "height" => camera.height,
        "aspect_ratio" => camera.aspect_ratio
      }
    end

    def numeric_close?(a, b, absolute = 1.0e-5, relative = 1.0e-7)
      av = a.to_f
      bv = b.to_f
      (av - bv).abs <= [absolute, relative * [av.abs, bv.abs, 1.0].max].max
    end

    def camera_states_equivalent?(before, after)
      return false unless before["perspective"] == after["perspective"]
      vector_keys = %w[eye target up]
      vectors_match = vector_keys.all? do |key|
        lhs = before[key]
        rhs = after[key]
        lhs.is_a?(Array) && rhs.is_a?(Array) && lhs.length == rhs.length &&
          lhs.zip(rhs).all? { |a, b| numeric_close?(a, b) }
      end
      return false unless vectors_match
      scalar_keys = ["aspect_ratio", before["perspective"] ? "fov" : "height"]
      scalar_keys.all? { |key| numeric_close?(before[key], after[key]) }
    end

    def restore_camera(state)
      c = Sketchup::Camera.new(
        Geom::Point3d.new(state.fetch("eye")),
        Geom::Point3d.new(state.fetch("target")),
        Geom::Vector3d.new(state.fetch("up"))
      )
      c.perspective = state.fetch("perspective")
      c.fov = state.fetch("fov") if c.perspective?
      c.height = state.fetch("height") unless c.perspective?
      c.aspect_ratio = state.fetch("aspect_ratio")
      model.active_view.camera = c
      true
    end

    def visual_state
      m = model
      ro = m.rendering_options
      si = m.shadow_info
      {
        "camera" => camera_state,
        "rendering" => VISUAL_RENDER_KEYS.each_with_object({}) { |k, h| h[k] = ro[k] if ro.keys.include?(k) },
        "shadow" => VISUAL_SHADOW_KEYS.each_with_object({}) { |k, h| h[k] = si[k] unless si[k].nil? },
        "selected_page" => m.pages.selected_page
      }
    end

    def restore_visual_state(state)
      m = model
      selected = state["selected_page"]
      m.pages.selected_page = selected if selected && selected.valid?
      state.fetch("rendering", {}).each { |k, v| m.rendering_options[k] = v }
      state.fetch("shadow", {}).each { |k, v| m.shadow_info[k] = v }
      restore_camera(state.fetch("camera"))
      m.active_view.invalidate
      true
    end

    def with_visual_state
      state = visual_state
      begin
        yield
      ensure
        restore_visual_state(state)
      end
    end

    # 设置透视相机：眼点、目标点、fov(度)。单位可省略。用于挑效果图视角。
    def camera(ex, ey, ez, tx, ty, tz, fov = 60, unit = nil)
      raise "fov 必须在 1..120 度之间" unless fov.to_f.between?(1.0, 120.0)
      model.active_view.camera = Sketchup::Camera.new(
        pt(ex, ey, ez, unit),
        pt(tx, ty, tz, unit),
        Geom::Vector3d.new(0, 0, 1),
        true, fov.to_f
      )
      true
    end

    # 效果图准备：临时设置带纹理着色/无边线/自动取景并截图；所有视图状态随后恢复。
    def render_ready(path = nil, width = 1600, height = 900)
      result = nil
      with_visual_state do
        style_material(true)
        model.rendering_options["DrawSilhouettes"] = false
        model.rendering_options["DrawBackEdges"] = false
        model.shadow_info["DisplayShadows"] = false
        model.active_view.zoom_extents
        c = model.active_view.camera
        model.active_view.camera = Sketchup::Camera.new(c.eye, c.target, c.up, true, c.fov) if c.perspective? == false
        with_temporarily_hidden_edges do
          result = screenshot(path, width, height)
        end
      end
      result
    end

    # 列出顶层实体（类型 | 计数 | 命名实体），用于反馈闭环核对。
    def list
      m = model
      counts = Hash.new(0)
      names = []
      m.entities.each do |e|
        t = e.respond_to?(:typename) ? e.typename : e.class.name
        counts[t] += 1
        names << "#{e.name} (#{t})" if e.respond_to?(:name) && !e.name.to_s.empty?
      end
      sum = counts.map { |k, v| "#{k}: #{v}" }.join(", ")
      ext = names.any? ? " | 命名实体: " + names.join(", ") : ""
      "顶层实体数: #{m.entities.count} (#{sum})#{ext}"
    end

    def current_revision
      model.get_attribute(ATTR_DICT, "revision", 0).to_i
    end

    def model_token
      ids = model.entities.map { |entity| entity.respond_to?(:persistent_id) ? entity.persistent_id : entity.entityID }
      "r#{current_revision}:#{model.entities.count}:#{ids.sort.join('-')}"
    end

    def info_data
      m = model
      options = m.options["UnitsOptions"]
      {
        "server_version" => SERVER_VERSION,
        "api_schema_version" => API_SCHEMA_VERSION,
        "sketchup_version" => Sketchup.version,
        "model_title" => m.title,
        "model_path" => m.path.to_s,
        "model_guid" => (m.respond_to?(:guid) ? m.guid : nil),
        "top_level_entity_count" => m.entities.count,
        "display_unit" => model_unit,
        "length_precision" => options["LengthPrecision"],
        "internal_length_unit" => "inch",
        "revision" => current_revision,
        "model_token" => model_token,
        "modified" => (m.respond_to?(:modified?) ? m.modified? : nil)
      }
    end

    def semantic_data(entity)
      {
        "spec_id" => entity.get_attribute(ATTR_DICT, "spec_id"),
        "kind" => entity.get_attribute(ATTR_DICT, "kind"),
        "level" => entity.get_attribute(ATTR_DICT, "level"),
        "certainty" => entity.get_attribute(ATTR_DICT, "certainty"),
        "source" => entity.get_attribute(ATTR_DICT, "source")
      }.reject { |_, value| value.nil? || value.to_s.empty? }
    end

    def mark_entity(entity, attributes)
      raise "目标实体无效" unless entity && entity.respond_to?(:valid?) && entity.valid?
      allowed = %w[spec_id kind level certainty source]
      attributes.each do |key, value|
        key = key.to_s
        next unless allowed.include?(key)
        entity.set_attribute(ATTR_DICT, key, value.nil? ? nil : value.to_s)
      end
      semantic_data(entity)
    end

    def entity_data(entity, unit = :model)
      record = {
        "persistent_id" => (entity.respond_to?(:persistent_id) ? entity.persistent_id : nil),
        "entity_id" => (entity.respond_to?(:entityID) ? entity.entityID : nil),
        "type" => (entity.respond_to?(:typename) ? entity.typename : entity.class.name),
        "name" => (entity.respond_to?(:name) ? entity.name.to_s : nil),
        "tag" => (entity.respond_to?(:layer) && entity.layer ? entity.layer.name : nil),
        "hidden" => (entity.respond_to?(:hidden?) ? entity.hidden? : nil),
        "locked" => (entity.respond_to?(:locked?) ? entity.locked? : nil),
        "material" => (entity.respond_to?(:material) && entity.material ? entity.material.name : nil),
        "semantic" => semantic_data(entity)
      }
      record["bounds"] = bounds_data(entity, unit) if entity.respond_to?(:bounds)
      record["solid"] = entity.manifold? if entity.respond_to?(:manifold?)
      record
    end

    def find_entity(reference)
      value = reference.to_s
      raise "实体引用不能为空" if value.empty?
      model.entities.find do |entity|
        semantic_data(entity)["spec_id"] == value ||
          (entity.respond_to?(:name) && entity.name.to_s == value) ||
          (entity.respond_to?(:persistent_id) && entity.persistent_id.to_s == value)
      end
    end

    def inspect_model_data(unit = :model)
      normalized = normalize_unit(unit, false)
      records = model.entities.map { |entity| entity_data(entity, normalized) }
      counts = Hash.new(0)
      records.each { |record| counts[record["type"]] += 1 }
      {
        "model" => info_data,
        "bounds" => bounds_data(nil, normalized),
        "counts" => counts,
        "entities" => records
      }
    end

    def validate_model_data(unit = :model)
      inspection = inspect_model_data(unit)
      records = inspection["entities"]
      issues = []
      spec_ids = records.map { |record| record.dig("semantic", "spec_id") }.compact
      duplicates = spec_ids.group_by { |value| value }.select { |_, values| values.length > 1 }.keys
      duplicates.each do |value|
        issues << { "severity" => "error", "code" => "duplicate_spec_id", "message" => "重复 spec_id: #{value}" }
      end
      records.each do |record|
        if %w[Group ComponentInstance].include?(record["type"]) && record["name"].to_s.empty?
          issues << { "severity" => "warning", "code" => "unnamed_container", "entity" => record["persistent_id"],
                      "message" => "组/组件未命名" }
        end
        bounds = record["bounds"]
        if bounds && [bounds["width"], bounds["depth"], bounds["height"]].all? { |value| value.to_f == 0.0 }
          issues << { "severity" => "warning", "code" => "zero_bounds", "entity" => record["persistent_id"],
                      "message" => "实体包围盒为零" }
        end
      end
      loose = records.count { |record| %w[Edge Face].include?(record["type"]) }
      if loose > 0
        issues << { "severity" => "warning", "code" => "loose_top_level_geometry",
                    "message" => "顶层存在 #{loose} 个松散边/面；建议分组" }
      end
      status = issues.any? { |issue| issue["severity"] == "error" } ? "fail" :
        (issues.empty? ? "pass" : "warn")
      {
        "status" => status,
        "revision" => current_revision,
        "model_token" => model_token,
        "issues" => issues,
        "summary" => { "top_level_entities" => records.length, "semantic_ids" => spec_ids.length }
      }
    end

    def plan_entity(reference, created)
      created[reference.to_s] || find_entity(reference)
    end

    def canonical_plan_value(value)
      case value
      when Hash
        value.keys.sort_by(&:to_s).each_with_object({}) do |key, sorted|
          sorted[key.to_s] = canonical_plan_value(value[key])
        end
      when Array
        value.map { |item| canonical_plan_value(item) }
      else
        value
      end
    end

    def apply_plan(plan)
      raise "plan 必须是对象" unless plan.is_a?(Hash)
      operations = plan["operations"]
      raise "operations 必须是数组" unless operations.is_a?(Array)
      raise "operations 不能为空" if operations.empty?
      raise "operations 超过 #{MAX_PLAN_OPERATIONS}" if operations.length > MAX_PLAN_OPERATIONS
      request_key = plan["idempotency_key"].to_s
      raise "idempotency_key 必填" if request_key.empty?
      raise "expected_revision 必填" unless plan.key?("expected_revision")
      unit = normalize_unit(plan["unit"], false)
      fingerprint = Digest::SHA256.hexdigest(JSON.generate(canonical_plan_value(
        { "unit" => unit, "operations" => operations }
      )))
      applied_revision = model.get_attribute(ATTR_DICT, "request:#{request_key}")
      if applied_revision
        applied_fingerprint = model.get_attribute(ATTR_DICT, "request:#{request_key}:fingerprint")
        if applied_fingerprint && applied_fingerprint != fingerprint
          raise "幂等键冲突：#{request_key} 已用于不同计划"
        end
        result = inspect_model_data(unit)
        result["idempotent_replay"] = true
        result["applied_revision"] = applied_revision.to_i
        result["idempotency_key"] = request_key
        return result
      end
      expected = plan["expected_revision"]
      if expected.to_i != current_revision
        raise "版本冲突：expected_revision=#{expected}，current_revision=#{current_revision}"
      end
      created = {}
      transaction(plan["label"] || "Codex structured plan") do
        operations.each_with_index do |action, index|
          raise "operation #{index} 必须是对象" unless action.is_a?(Hash)
          type = action["type"].to_s
          id = action["id"].to_s
          action_unit = normalize_unit(action["unit"] || unit, false)
          result = case type
                   when "set_units"
                     set_units(action["unit"] || unit, action.fetch("precision", 3))
                   when "material"
                     if action.key?("metallic") || action.key?("roughness")
                       mat_pbr(action.fetch("name"), action.fetch("color"), action["metallic"],
                               action["roughness"], action["alpha"])
                     else
                       mat(action.fetch("name"), action.fetch("color"), action["alpha"])
                     end
                   when "box"
                     box(action.fetch("name", id), action.fetch("x"), action.fetch("y"), action.fetch("z"),
                         action.fetch("width"), action.fetch("depth"), action.fetch("height"), action_unit)
                   when "cylinder"
                     cylinder(action.fetch("name", id), action.fetch("x"), action.fetch("y"), action.fetch("z"),
                              action.fetch("radius"), action.fetch("height"), action.fetch("segments", 32), action_unit)
                   when "cone"
                     cone(action.fetch("name", id), action.fetch("x"), action.fetch("y"), action.fetch("z"),
                          action.fetch("radius"), action.fetch("height"), action.fetch("segments", 32), action_unit)
                   when "ngon"
                     ngon(action.fetch("name", id), action.fetch("x"), action.fetch("y"), action.fetch("z"),
                          action.fetch("radius"), action.fetch("sides", 6), action["height"], action_unit)
                   when "curve"
                     curve(action.fetch("name", id), action.fetch("points"), action_unit)
                   when "move"
                     move(plan_entity(action.fetch("target"), created), action.fetch("dx"), action.fetch("dy"),
                          action.fetch("dz"), action_unit)
                   when "rotate"
                     rotate(plan_entity(action.fetch("target"), created), action.fetch("degrees"),
                            action.fetch("axis", "z"))
                   when "assign_material"
                     target = plan_entity(action.fetch("target"), created)
                     material_ref = action.fetch("material").to_s
                     material = created[material_ref] || model.materials[material_ref]
                     raise "未找到材质: #{material_ref}" unless material
                     set_mat(target, material)
                     target
                   when "mark"
                     target = plan_entity(action.fetch("target"), created)
                     mark_entity(target, action.fetch("attributes", {}))
                     target
                   when "erase"
                     target = plan_entity(action.fetch("target"), created)
                     target.erase!
                     true
                   else
                     raise "不支持的 operation type: #{type}"
                   end
          created[id] = result unless id.empty?
          if result.respond_to?(:set_attribute) && action["semantic"].is_a?(Hash)
            mark_entity(result, action["semantic"])
          end
        end
        next_revision = current_revision + 1
        model.set_attribute(ATTR_DICT, "revision", next_revision)
        model.set_attribute(ATTR_DICT, "request:#{request_key}", next_revision)
        model.set_attribute(ATTR_DICT, "request:#{request_key}:fingerprint", fingerprint)
      end
      result = inspect_model_data(unit)
      result["idempotent_replay"] = false
      result["idempotency_key"] = request_key
      result["created_ids"] = created.keys
      result
    end

    def capabilities_data
      {
        "server_version" => SERVER_VERSION,
        "schema_version" => API_SCHEMA_VERSION,
        "internal_length_unit" => "inch",
        "required_plan_units" => UNIT_FACTOR.keys,
        "structured_operations" => %w[set_units material box cylinder cone ngon curve move rotate assign_material mark erase],
        "raw_eval" => true,
        "raw_eval_warning" => "Raw eval is an expert fallback; prefer apply_plan for rollback, revision and idempotency.",
        "max_plan_operations" => MAX_PLAN_OPERATIONS
      }
    end

    # ---------- 高级几何（曲面/形体） ----------

    # 光滑圆柱：(x,y,z) 底面圆心，半径 r，高 h；segs 分段越多越圆
    def cylinder(name, x, y, z, r, h, segs = 32, unit = nil)
      raise "半径/高必须 > 0" if r.to_f <= 0 || h.to_f <= 0
      g = entities.add_group
      g.name = name.to_s
      c = pt(x, y, z, unit)
      edges = g.entities.add_circle(c, Geom::Vector3d.new(0, 0, 1), conv(r, unit), segs.to_i)
      face = g.entities.add_face(edges)
      face.reverse! if face.normal.z < 0
      face.pushpull(conv(h, unit))
      smooth(g, 22)
      g
    end

    # 圆锥（底面圆 + 顶点）：用 PolygonMesh 生成，侧面自动平滑
    def cone(name, x, y, z, r, h, segs = 32, unit = nil)
      raise "半径/高必须 > 0" if r.to_f <= 0 || h.to_f <= 0
      c = pt(x, y, z, unit)
      rad = conv(r, unit)
      hh = conv(h, unit)
      mesh = Geom::PolygonMesh.new
      base = []
      segs.to_i.times do |i|
        t = 2.0 * Math::PI * i / segs.to_f
        base << mesh.add_point(Geom::Point3d.new(c.x + rad * Math.cos(t), c.y + rad * Math.sin(t), c.z))
      end
      apex = mesh.add_point(Geom::Point3d.new(c.x, c.y, c.z + hh))
      segs.to_i.times do |i|
        mesh.add_polygon(base[i], base[(i + 1) % segs], apex)
      end
      mesh.add_polygon(base.reverse)   # 底面，法线朝下
      g = entities.add_group
      g.name = name.to_s
      g.entities.add_faces_from_mesh(mesh, Geom::PolygonMesh::AUTO_SOFTEN | Geom::PolygonMesh::SMOOTH_SOFT_EDGES)
      smooth(g, 22)
      g
    end

    # 光滑球体：经纬网格，lon 经向分段，lat 纬向分段
    def sphere(name, cx, cy, cz, r, lon = 24, lat = 16, unit = nil)
      center = pt(cx, cy, cz, unit)
      rad = conv(r, unit)
      lon = lon.to_i
      lat = [lat.to_i, 3].max
      mesh = Geom::PolygonMesh.new
      bottom = mesh.add_point(Geom::Point3d.new(center.x, center.y, center.z - rad))
      top = mesh.add_point(Geom::Point3d.new(center.x, center.y, center.z + rad))
      rows = []
      (1...lat).each do |j|
        phi = Math::PI * j / lat
        z = center.z + rad * Math.cos(phi)
        rr = rad * Math.sin(phi)
        row = []
        lon.times do |i|
          th = 2.0 * Math::PI * i / lon
          row << mesh.add_point(Geom::Point3d.new(center.x + rr * Math.cos(th), center.y + rr * Math.sin(th), z))
        end
        rows << row
      end
      if rows.any?
        rows[0].each_with_index do |_idx, i|
          mesh.add_polygon(bottom, rows[0][(i + 1) % lon], rows[0][i])
        end
        (0...(rows.length - 1)).each do |j|
          a = rows[j]
          b = rows[j + 1]
          lon.times do |i|
            i2 = (i + 1) % lon
            mesh.add_polygon(a[i], b[i], b[i2], a[i2])
          end
        end
        last = rows[-1]
        last.each_with_index do |_idx, i|
          mesh.add_polygon(top, last[i], last[(i + 1) % lon])
        end
      end
      g = entities.add_group
      g.name = name.to_s
      g.entities.add_faces_from_mesh(mesh, Geom::PolygonMesh::AUTO_SOFTEN | Geom::PolygonMesh::SMOOTH_SOFT_EDGES)
      g.entities.grep(Sketchup::Face).each do |f|
        c0 = f.bounds.center
        f.reverse! if f.normal.dot(c0 - center) < 0
      end
      g
    end

    # 参数化曲面（地形/拱顶/波浪等）：x0,y0..x1,y1 为平面范围，zgrid 为 ny×nx 的高度矩阵（单位随 unit）
    def surface(name, x0, y0, x1, y1, zgrid, unit = nil)
      ny = zgrid.length
      raise "zgrid 至少 2 行" if ny < 2
      nx = zgrid[0].length
      raise "zgrid 每行长度一致且至少 2" if nx < 2 || zgrid.any? { |r| r.length != nx }
      sx = (x1 - x0).to_f / (nx - 1)
      sy = (y1 - y0).to_f / (ny - 1)
      ox = conv(x0, unit)
      oy = conv(y0, unit)
      sx = conv(sx, unit)
      sy = conv(sy, unit)
      mesh = Geom::PolygonMesh.new
      ids = []
      (0...ny).each do |j|
        row = []
        (0...nx).each do |i|
          z = conv(zgrid[j][i], unit)
          row << mesh.add_point(Geom::Point3d.new(ox + i * sx, oy + j * sy, z))
        end
        ids << row
      end
      (0...(ny - 1)).each do |j|
        (0...(nx - 1)).each do |i|
          mesh.add_polygon(ids[j][i], ids[j][i + 1], ids[j + 1][i + 1], ids[j + 1][i])
        end
      end
      g = entities.add_group
      g.name = name.to_s
      g.entities.add_faces_from_mesh(mesh, Geom::PolygonMesh::AUTO_SOFTEN | Geom::PolygonMesh::SMOOTH_SOFT_EDGES)
      g.entities.grep(Sketchup::Face).each { |f| f.reverse! if f.normal.z < 0 }
      g
    end

    # 放样：rings 为多个截面环（每个环是 [x,y,z] 数组，各环点数一致），生成光滑表面
    def loft(name, rings, unit = nil)
      pts = rings.map { |r| r.map { |p| pt(p[0], p[1], p[2], unit) } }
      n = pts[0].length
      raise "每个环至少 2 点且各环点数一致" if n < 2 || pts.any? { |r| r.length != n }
      mesh = Geom::PolygonMesh.new
      idx = pts.map { |ring| ring.map { |p| mesh.add_point(p) } }
      (0...(pts.length - 1)).each do |k|
        a = idx[k]
        b = idx[k + 1]
        n.times do |i|
          i2 = (i + 1) % n
          mesh.add_polygon(a[i], b[i], b[i2], a[i2])
        end
      end
      g = entities.add_group
      g.name = name.to_s
      g.entities.add_faces_from_mesh(mesh, Geom::PolygonMesh::AUTO_SOFTEN | Geom::PolygonMesh::SMOOTH_SOFT_EDGES)
      g
    end

    # 折线/曲线（用于轮廓、路径）；返回组
    def curve(name, pts, unit = nil)
      g = entities.add_group
      g.name = name.to_s
      g.entities.add_curve(pts.map { |p| pt(p[0], p[1], p[2], unit) })
      g
    end

    # 多边柱（低多边形圆柱/棱柱）：sides 边数，h 高
    def ngon(name, x, y, z, r, sides = 32, h = nil, unit = nil)
      g = entities.add_group
      g.name = name.to_s
      c = pt(x, y, z, unit)
      edges = g.entities.add_ngon(c, Geom::Vector3d.new(0, 0, 1), conv(r, unit), sides.to_i)
      face = g.entities.add_face(edges)
      face.reverse! if face.normal.z < 0
      face.pushpull(conv(h, unit)) if h && h.to_f > 0
      smooth(g, 20)
      g
    end

    # 把参考图/平面图放进模型（用作图像驱动建模的参照），返回组
    def add_image(path, x, y, z, width, height = 0.0, unit = nil)
      g = entities.add_group
      g.name = "image_" + File.basename(path, ".*")
      g.entities.add_image(path, pt(x, y, z, unit), conv(width, unit), height.to_f == 0.0 ? 0.0 : conv(height, unit))
      g
    end

    # ---------- 变换 ----------

    def copy(inst, dx, dy, dz, unit = nil)
      k = inst.copy
      k.transform!(Geom::Transformation.new([conv(dx, unit), conv(dy, unit), conv(dz, unit)]))
      k
    end

    def scale(inst, sx, sy, sz, center = nil)
      inst.transform!(Geom::Transformation.scaling(center || ORIGIN, sx.to_f, sy.to_f, sz.to_f))
      inst
    end

    def array(inst, count, dx, dy, dz, unit = nil)
      res = []
      (1..count.to_i).each do |i|
        k = inst.copy
        k.transform!(Geom::Transformation.new([conv(dx, unit) * i, conv(dy, unit) * i, conv(dz, unit) * i]))
        res << k
      end
      res
    end

    # ---------- 平滑/软化（提升曲面质感） ----------

    # 把角度小于 angle(度) 的相邻面之间的边设为软化+平滑
    def smooth(obj, angle_deg = 30)
      es = obj.is_a?(Sketchup::Group) ? obj.entities : obj
      angle = angle_deg.to_f.degrees
      es.grep(Sketchup::Face).each do |f|
        f.edges.each do |e|
          next if e.soft? && e.smooth?
          nbr = e.faces.find { |x| x != f && x.is_a?(Sketchup::Face) }
          next unless nbr
          if f.normal.angle_between(nbr.normal) <= angle
            e.soft = true
            e.smooth = true
          end
        end
      end
      true
    end

    def soft(obj, on = true)
      es = obj.is_a?(Sketchup::Group) ? obj.entities : obj
      es.grep(Sketchup::Face).each do |f|
        f.edges.each { |e| e.soft = on; e.smooth = on }
      end
      true
    end

    # ---------- 材质（颜色 / PBR / 纹理 / 透明度） ----------

    def mat_rgb(name, r, g, b, alpha = nil)
      m = model
      material = m.materials[name.to_s] || m.materials.add(name.to_s)
      material.color = Sketchup::Color.new(r.to_i, g.to_i, b.to_i)
      material.alpha = alpha if alpha
      material
    end

    # PBR：metallic 金属度 0~1，roughness 粗糙度 0~1（越光滑越小）
    def mat_pbr(name, hex_color, metallic = nil, roughness = nil, alpha = nil)
      material = mat(name, hex_color, alpha)
      if metallic
        value = metallic.to_f
        raise "metallic 必须在 0..1" unless value.between?(0.0, 1.0)
        raise "当前 SketchUp 不支持 PBR metallic" unless material.respond_to?(:metallic_factor=)
        material.metalness_enabled = true if material.respond_to?(:metalness_enabled=)
        material.metallic_factor = value
      end
      if roughness
        value = roughness.to_f
        raise "roughness 必须在 0..1" unless value.between?(0.0, 1.0)
        raise "当前 SketchUp 不支持 PBR roughness" unless material.respond_to?(:roughness_factor=)
        material.roughness_enabled = true if material.respond_to?(:roughness_enabled=)
        material.roughness_factor = value
      end
      material
    end

    # 图像纹理：width/height 为纹理的真实铺贴尺寸；unit=nil 兼容为裸英寸。
    def mat_tex(name, path, width = nil, height = nil, unit = nil)
      raise "贴图不存在: #{path}" unless File.file?(path.to_s)
      m = model
      material = m.materials[name.to_s] || m.materials.add(name.to_s)
      material.texture = path
      if width
        texture = material.texture
        raise "SketchUp 未能读取贴图: #{path}" unless texture
        w = conv(width, unit)
        h = height ? conv(height, unit) : nil
        texture.size = h ? [w, h] : w
      end
      material
    end

    # 给实体（组/实体集/面）整套材质（正反面）
    def set_mat(obj, material)
      mat_obj = if material.is_a?(Sketchup::Material)
                  material
                else
                  model.materials[material.to_s] || raise("未找到材质: #{material}")
                end
      es = obj.is_a?(Sketchup::Group) ? obj.entities : obj
      es.grep(Sketchup::Face).each do |f|
        f.material = mat_obj
        f.back_material = mat_obj
      end
      true
    end

    # ---------- 场景 / 阴影 / 取景 ----------

    def scene(name)
      page_name = name.to_s
      raise "场景名不能为空" if page_name.empty?
      model.pages.find { |p| p.name == page_name } || model.pages.add(page_name)
    end

    def shadow(on = true, time = nil)
      si = model.shadow_info
      si["DisplayShadows"] = on
      si["ShadowTime_Day"] = time if time
      true
    end

    def style_material(shaded = true)
      ro = model.rendering_options
      ro["RenderMode"] = shaded ? 3 : 5 # Smooth shaded / monochrome
      ro["Texture"] = !!shaded
      true
    end

    def zoom(obj = nil)
      av = model.active_view
      if obj.respond_to?(:bounds)
        av.zoom(obj.bounds)
      else
        av.zoom_extents
      end
      true
    end

    # ---------- 精度（单位/精确量取） ----------

    UNIT_CODE = { "in" => 0, "inch" => 0, "ft" => 1, "feet" => 1, "mm" => 2, "millimeter" => 2,
                  "cm" => 3, "centimeter" => 3, "m" => 4, "meter" => 4 }

    # 设定模型长度单位与显示精度（十进制）。让模型和 AI 用同一套单位，出图/量取更准。
    def set_units(unit = :mm, precision = 3)
      normalized = normalize_unit(unit, false)
      o = model.options["UnitsOptions"]
      o["LengthUnit"] = UNIT_CODE.fetch(normalized)
      o["LengthFormat"] = 0          # 0 = 十进制
      o["LengthPrecision"] = precision.to_i.clamp(0, 8)
      o["SuppressUnitsDisplay"] = false
      raise "单位设置未生效" unless model_unit == normalized
      true
    end

    # 当前单位/精度摘要
    def units_info
      o = model.options["UnitsOptions"]
      names = { 0 => "英寸", 1 => "英尺", 2 => "毫米", 3 => "厘米", 4 => "米" }
      "长度单位: #{names[o['LengthUnit']] || o['LengthUnit']} | 显示精度: #{o['LengthPrecision']} 位 | 格式: #{o['LengthFormat']}"
    end

    def bounds_data(obj = nil, unit = nil)
      bb = (obj && obj.respond_to?(:bounds)) ? obj.bounds : model.bounds
      normalized = normalize_unit(unit)
      display_unit = normalized || "in_raw"
      factor = normalized ? UNIT_FACTOR.fetch(normalized) : 1.0
      convert = ->(v) { (v.to_f / factor).round(6) }
      {
        "unit" => display_unit,
        # SketchUp BoundingBox names its Y extent `height` and its Z extent
        # `depth`.  Translate those API names to architectural width/depth/height.
        "width" => convert.call(bb.width),
        "depth" => convert.call(bb.height),
        "height" => convert.call(bb.depth),
        "min" => [convert.call(bb.min.x), convert.call(bb.min.y), convert.call(bb.min.z)],
        "max" => [convert.call(bb.max.x), convert.call(bb.max.y), convert.call(bb.max.z)]
      }
    end

    # unit=nil 明确返回 in_raw；如需当前显示单位请传 :model。
    def bounds(obj = nil, unit = nil)
      data = bounds_data(obj, unit)
      "尺寸(宽x深x高): #{data['width']} x #{data['depth']} x #{data['height']} (单位:#{data['unit']}) | " \
        "范围: (#{data['min'].join(',')})..(#{data['max'].join(',')})"
    end

    # 按名称量取某个实体/组的精确尺寸
    def dim(name, unit = nil)
      g = entities.find { |e| e.respond_to?(:name) && e.name.to_s == name.to_s }
      g ? bounds(g, unit) : "未找到实体: #{name}"
    end

    # 两点距离（输入按 unit 换算，结果同样按 unit 显示）
    def dist(a, b, unit = nil)
      p1 = pt(a[0], a[1], a[2], unit)
      p2 = pt(b[0], b[1], b[2], unit)
      d = (p1 - p2).length
      normalized = normalize_unit(unit)
      d2 = normalized ? (d / UNIT_FACTOR.fetch(normalized)) : d
      d2.round(6)
    end

    # 可选网格吸附：把数值按 grid 取整（用于把尺寸/坐标归一，保证干净）
    def snap(value, grid)
      g = grid.to_f
      (value.to_f / g).round * g
    end

    # 读回实体/组的实际原点（验证是否放到目标位置）
    def locate(inst, unit = nil)
      o = inst.transformation.origin
      normalized = normalize_unit(unit)
      f = normalized ? UNIT_FACTOR.fetch(normalized) : 1.0
      label = normalized || "in_raw"
      "原点: (#{(o.x / f).round(6)}, #{(o.y / f).round(6)}, #{(o.z / f).round(6)}) (单位:#{label})"
    end

    # 参考点（构造点，不生成面）：用于把图上量到的坐标精确标到模型
    def gpoint(x, y, z, unit = nil)
      entities.add_cpoint(pt(x, y, z, unit))
    end

    # 参考线（构造线）：用于描墙轴/延长线/对齐参考
    def gline(x1, y1, z1, x2, y2, z2, unit = nil)
      entities.add_cline(pt(x1, y1, z1, unit), pt(x2, y2, z2, unit))
    end

    # 地面测量网格（构造线）：把参考图按比例映射到模型坐标后，用网格对位/描线
    def grid(name, x, y, z, w, d, step, unit = nil)
      g = entities.add_group
      g.name = name.to_s
      ox = conv(x, unit); oy = conv(y, unit); oz = conv(z, unit)
      ww = conv(w, unit); dd = conv(d, unit); sp = conv(step, unit)
      sp = sp <= 0 ? 1.0 : sp
      gx = ox
      while gx <= ox + ww + 1e-9
        g.entities.add_cline(Geom::Point3d.new(gx, oy, oz), Geom::Point3d.new(gx, oy + dd, oz))
        gx += sp
      end
      gy = oy
      while gy <= oy + dd + 1e-9
        g.entities.add_cline(Geom::Point3d.new(ox, gy, oz), Geom::Point3d.new(ox + ww, gy, oz))
        gy += sp
      end
      g
    end

    # 无副作用自检：所有测试几何最终 abort，视图/单位状态在 ensure 中恢复。
    def selftest
      m = model
      before_count = m.entities.count
      visual_before = visual_state
      units_provider = m.options["UnitsOptions"]
      units_before = units_provider.to_a.to_h
      temp_path = File.join(Sketchup.temp_dir, "su_selftest_#{Process.pid}_#{Time.now.to_i}.png")
      res = {}
      operation_started = false
      overall_error = nil
      check = lambda do |name, &block|
        begin
          block.call
          res[name] = "OK"
        rescue => e
          res[name] = "ERR #{e.class}: #{e.message}"
        end
      end

      begin
        m.start_operation("SU SELFTEST (ROLLBACK)", true)
        operation_started = true

        check.call("units") do
          set_units(:mm, 3)
          raise "LengthPrecision 未生效" unless units_provider["LengthPrecision"] == 3
          raise "1m 换算错误" unless (conv(1, :m) - 39.37007874015748).abs < 1e-8
        end

        floor = nil
        column = nil
        check.call("geometry/material") do
          floor = box("ST_地坪", 0, 0, 0, 8, 6, 0.2, :m)
          column = cylinder("ST_柱", 6.5, 5.3, 0.2, 0.4, 3, 24, :m)
          set_mat(floor, mat("ST_墙", "#e8e2d7"))
          pbr = mat_pbr("ST_金属", "#b8bcc0", 0.85, 0.25)
          set_mat(column, pbr)
          raise "PBR metallic 未启用" if pbr.respond_to?(:metalness_enabled?) && !pbr.metalness_enabled?
          raise "PBR roughness 未启用" if pbr.respond_to?(:roughness_enabled?) && !pbr.roughness_enabled?
          data = bounds_data(floor, :m)
          raise "盒体尺寸错误: #{data.inspect}" unless (data["width"] - 8.0).abs < 1e-5 && (data["depth"] - 6.0).abs < 1e-5
        end

        texture_path = File.join(__dir__, "textures", "concrete.png")
        if File.file?(texture_path)
          check.call("texture") do
            tex = mat_tex("ST_混凝土", texture_path, 1, 1, :m)
            raise "纹理宽度错误" unless (tex.texture.width.to_f - conv(1, :m)).abs < 1e-5
            set_mat(floor, tex) if floor
          end
        else
          # The public source release excludes unverified image assets. Geometry
          # remains in its solid-color material; a skipped texture is not verified.
          res["texture"] = "SKIP sample texture not installed (solid-color material retained)"
        end

        check.call("render_restore") do
          state = visual_state
          render_ready(temp_path, 640, 360)
          raise "截图未生成" unless File.file?(temp_path)
          after = visual_state
          raise "相机未恢复" unless camera_states_equivalent?(state["camera"], after["camera"])
          raise "渲染选项未恢复" unless state["rendering"] == after["rendering"]
          raise "阴影状态未恢复" unless state["shadow"] == after["shadow"]
        end
      rescue => e
        overall_error = "#{e.class}: #{e.message}"
      ensure
        begin
          m.abort_operation if operation_started
        rescue => e
          overall_error ||= "回滚失败 #{e.class}: #{e.message}"
        end
        begin
          units_before.each { |k, v| units_provider[k] = v }
          restore_visual_state(visual_before)
        rescue => e
          overall_error ||= "状态恢复失败 #{e.class}: #{e.message}"
        end
        File.delete(temp_path) if File.file?(temp_path)
      end

      res["no_side_effect"] = m.entities.count == before_count ? "OK" : "ERR 顶层实体数发生变化"
      fails = res.select { |_, value| value.start_with?("ERR") }
      skips = res.select { |_, value| value.start_with?("SKIP") }
      summary = res.map { |k, v| "#{k}=#{v}" }.join(" | ")
      if overall_error
        "SELFTEST ERROR: #{overall_error}\n#{summary}"
      elsif fails.empty?
        "SELFTEST PASS (ROLLED BACK; #{skips.length} SKIPPED) ✅\n#{summary}"
      else
        "SELFTEST FAIL (ROLLED BACK) ❌ (#{fails.length})\n#{summary}"
      end
    end

    # 安全事务：成功提交；任何异常整体回滚并重新抛出。
    def transaction(label = "AI 操作")
      raise "不允许嵌套 SU 事务" if manual_operation_open
      m = model
      m.start_operation(label.to_s, true)
      begin
        result = yield
        m.commit_operation
        result
      rescue Exception
        m.abort_operation
        raise
      end
    end

    alias with_operation transaction

    # 兼容旧调用 Su.undo ... Su.commit。新代码应优先使用 Su.transaction { ... }。
    def undo(label = "AI 操作")
      raise "已有未结束事务" if manual_operation_open
      model.start_operation(label.to_s, true)
      self.manual_operation_open = true
      true
    end

    def commit
      raise "没有由 Su.undo 打开的事务" unless manual_operation_open
      model.commit_operation
      self.manual_operation_open = false
      true
    end

    def abort
      return false unless manual_operation_open
      model.abort_operation
      self.manual_operation_open = false
      true
    end

    # 保存；path 省略时存到当前文件旁（无则桌面）的 原名_时间戳.skp，返回保存路径
    def save(path = nil)
      m = model
      unless path
        dir = m.path.to_s.empty? ? File.join(Dir.home, "Desktop") : File.dirname(m.path)
        base = m.path.to_s.empty? ? "ai_model" : File.basename(m.path, ".skp")
        path = File.join(dir, "#{base}_#{Time.now.strftime('%Y%m%d_%H%M%S')}.skp")
      end
      m.save(path)
      path
    end

    # 清空当前模型内容（不可撤销）
    def reset
      entities.clear!
      true
    end

    # 弹窗提示（会阻塞到用户点击，自动化中尽量少用）
    def msg(text)
      UI.messagebox(text.to_s)
    end

    # 把当前视图截图保存为 PNG；path 省略时存桌面 su_view_时间戳.png，返回保存路径。
    # 用于“建模→截图→AI 查看→调整”的反馈闭环。
    def screenshot(path = nil, width = 1600, height = 900)
      unless path
        dir = File.join(Dir.home, "Desktop")
        path = File.join(dir, "su_view_#{Time.now.strftime('%Y%m%d_%H%M%S')}.png")
      end
      model.active_view.write_image(path, width.to_i, height.to_i, true, 0.9)
      File.exist?(path) ? path : nil
    end

    def preset_camera(name)
      bb = model.bounds
      center = bb.center
      extent = [bb.width.to_f, bb.depth.to_f, bb.height.to_f, 120.0].max
      distance = extent * 2.2
      key = name.to_s.downcase
      eye, up, perspective = case key
                             when "front"
                               [Geom::Point3d.new(center.x, center.y - distance, center.z),
                                Geom::Vector3d.new(0, 0, 1), false]
                             when "back"
                               [Geom::Point3d.new(center.x, center.y + distance, center.z),
                                Geom::Vector3d.new(0, 0, 1), false]
                             when "left"
                               [Geom::Point3d.new(center.x - distance, center.y, center.z),
                                Geom::Vector3d.new(0, 0, 1), false]
                             when "right"
                               [Geom::Point3d.new(center.x + distance, center.y, center.z),
                                Geom::Vector3d.new(0, 0, 1), false]
                             when "top"
                               [Geom::Point3d.new(center.x, center.y, center.z + distance),
                                Geom::Vector3d.new(0, 1, 0), false]
                             else
                               [Geom::Point3d.new(center.x + distance, center.y - distance, center.z + distance * 0.72),
                                Geom::Vector3d.new(0, 0, 1), true]
                             end
      camera = Sketchup::Camera.new(eye, center, up)
      camera.perspective = perspective
      camera.fov = 50.0 if perspective
      camera.height = extent * 1.25 unless perspective
      model.active_view.camera = camera
      model.active_view.zoom_extents
      true
    end

    def capture_views_data(views = nil, directory = nil, width = 1600, height = 900, clean = true)
      requested = views.is_a?(Array) && !views.empty? ? views : %w[iso front right top]
      raise "最多一次拍摄 12 个视图" if requested.length > 12
      directory ||= File.join(Dir.home, "Desktop", "Codex-SU-Views-#{Time.now.strftime('%Y%m%d_%H%M%S')}")
      FileUtils.mkdir_p(directory)
      outputs = []
      with_visual_state do
        requested.each_with_index do |item, index|
          spec = item.is_a?(Hash) ? item : { "preset" => item.to_s, "name" => item.to_s }
          name = (spec["name"] || spec["preset"] || "view_#{index + 1}").to_s
          safe_name = name.gsub(/[^0-9A-Za-z_\-\u4e00-\u9fff]+/, "_")
          if spec["eye"].is_a?(Array) && spec["target"].is_a?(Array)
            unit = normalize_unit(spec["unit"], false)
            eye = pt(*spec["eye"], unit)
            target = pt(*spec["target"], unit)
            up_values = spec["up"].is_a?(Array) ? spec["up"] : [0, 0, 1]
            camera = Sketchup::Camera.new(eye, target, Geom::Vector3d.new(*up_values))
            camera.perspective = spec.fetch("perspective", true)
            camera.fov = spec.fetch("fov", 50).to_f if camera.perspective?
            model.active_view.camera = camera
            model.active_view.zoom_extents if spec.fetch("zoom_extents", false)
          else
            preset_camera(spec["preset"] || "iso")
          end
          output_path = File.join(directory, format("%02d_%s.png", index + 1, safe_name))
          captured = clean ? render_ready(output_path, width, height) : screenshot(output_path, width, height)
          raise "视图截图失败: #{name}" unless captured && File.file?(captured)
          outputs << {
            "name" => name,
            "preset" => spec["preset"],
            "path" => captured,
            "clean_render" => !!clean,
            "camera" => camera_state
          }
        end
      end
      { "directory" => directory, "views" => outputs, "restored_original_view" => true }
    end

    # 当前模型摘要：名称 / 路径 / 顶层实体数 / 长度单位
    def info
      m = model
      "模型名: #{m.title} | 路径: #{m.path.to_s.empty? ? '(未保存)' : m.path} | 顶层实体数: #{m.entities.count} | 长度单位: #{m.options['UnitsOptions']['LengthUnit']}"
    end

    def dispatch_call(method, args = {})
      args = {} unless args.is_a?(Hash)
      case method.to_s
      when "capabilities"
        capabilities_data
      when "info"
        info_data
      when "inspect_model"
        inspect_model_data(args["unit"] || :model)
      when "validate_model"
        validate_model_data(args["unit"] || :model)
      when "apply_plan"
        apply_plan(args.fetch("plan"))
      when "capture_views"
        capture_views_data(args["views"], args["directory"], args.fetch("width", 1600),
                           args.fetch("height", 900), args.fetch("clean", true))
      when "screenshot"
        { "path" => screenshot(args["path"], args.fetch("width", 1600), args.fetch("height", 900)) }
      when "render_ready"
        { "path" => render_ready(args["path"], args.fetch("width", 1600), args.fetch("height", 900)),
          "restored_visual_state" => true }
      when "save"
        { "path" => save(args["path"]), "revision" => current_revision }
      when "bounds"
        target = args["reference"].to_s.empty? ? nil : find_entity(args["reference"])
        raise "未找到实体: #{args['reference']}" if args["reference"] && !target
        bounds_data(target, args["unit"] || :model)
      when "selftest"
        { "summary" => selftest }
      else
        raise "未知结构化方法: #{method}"
      end
    end

    # ---------------- HTTP 服务 ----------------
    # 注意：SketchUp 控制台里后台线程得不到调度，所以这里不用 Thread，
    # 而是用 UI.start_timer 定时器（由主界面事件循环驱动，保证执行）。
    # 每次回调非阻塞地检查并处理连接，不会卡住 SketchUp 界面。

    def start_server
      server = TCPServer.new("127.0.0.1", PORT)
      self.server = server
      self.timer_id = UI.start_timer(0.2, true) { poll_server }
      puts "Su AI server 已启动（定时器模式）: http://127.0.0.1:#{PORT}（Su 辅助函数可用）"
    end

    def stop_server
      UI.stop_timer(timer_id) if timer_id
      server.close unless server.nil? || server.closed?
      self.server = nil
      self.timer_id = nil
      puts "Su AI server 已停止"
    rescue => e
      puts "停止失败: #{e.message}"
    end

    # 定时器回调：处理所有排队中的连接
    def poll_server
      return if server.nil? || server.closed?
      loop do
        ready = IO.select([server], nil, nil, 0)
        break unless ready
        client = begin
          server.accept_nonblock
        rescue IO::WaitReadable, Errno::ECONNABORTED
          break
        end
        handle_client(client)
      end
    end

    # 处理单个 HTTP 连接（同步、非阻塞读取，5 秒总超时）
    def handle_client(client)
      begin
        request = read_request(client)
        if request.nil?
          client.close
          return
        end
        method, path, body = request
        if method == "GET" && path == "/ping"
          respond(client, { "status" => "ok" })
        elsif method == "POST" && path == "/call"
          begin
            body.force_encoding("UTF-8")
            request_data = JSON.parse(body)
            result = dispatch_call(request_data.fetch("method"), request_data["args"] || {})
            respond(client, { "status" => "ok", "result" => result })
          rescue Exception => e
            respond(client, { "status" => "error", "error" => safe_json_str("#{e.class}: #{e.message}") })
          end
        elsif method == "POST" && path == "/eval"
          begin
            # 客户端按 UTF-8 发送代码；不强制的话含中文的代码会被当作 ASCII-8BIT，
            # 中文实体名、字符串拼接/插值会抛 Encoding::CompatibilityError
            body.force_encoding("UTF-8")
            result = eval(body, TOPLEVEL_BINDING)
            respond(client, { "status" => "ok", "result" => safe_json_str(result.inspect) })
          rescue Exception => e
            abort if manual_operation_open
            respond(client, { "status" => "error", "error" => safe_json_str("#{e.class}: #{e.message}") })
          end
        else
          respond(client, { "status" => "error", "error" => "404 #{method} #{path}" })
        end
      rescue => e
        # 单个连接出错不影响服务
      ensure
        client.close unless client.nil? || client.closed?
      end
    end

    # 非阻塞读取完整请求（请求行 + 请求头 + body），总超时 5 秒；返回 [method, path, body] 或 nil
    def read_request(client)
      buffer = "".b  # 二进制缓冲：中文请求体是 UTF-8 字节，二进制拼接不会触发编码兼容错误
      deadline = Time.now + 5.0
      while (remaining = deadline - Time.now) > 0
        ready = IO.select([client], nil, nil, remaining)
        return nil if ready.nil?
        begin
          buffer << client.read_nonblock(65536)
        rescue IO::WaitReadable
          next
        rescue EOFError, Errno::ECONNRESET, Errno::EPIPE
          return nil
        end

        # 请求头是否收全
        head_end = nil
        sep_len = 0
        if (i = buffer.index("\r\n\r\n"))
          head_end = i
          sep_len = 4
        elsif (i = buffer.index("\n\n"))
          head_end = i
          sep_len = 2
        end
        next unless head_end

        head = buffer[0, head_end]
        rest = buffer[(head_end + sep_len)..-1] || "".b
        lines = head.split(/\r?\n/)
        method, path = lines[0].split(" ")
        content_length = 0
        lines[1..-1].to_a.each do |h|
          k, v = h.split(":", 2)
          content_length = v.to_i if k && k.downcase.strip == "content-length"
        end
        raise "请求体超过 #{MAX_REQUEST_BYTES} 字节" if content_length > MAX_REQUEST_BYTES
        while rest.length < content_length
          remaining = deadline - Time.now
          return nil if remaining <= 0
          ready = IO.select([client], nil, nil, remaining)
          return nil if ready.nil?
          begin
            rest << client.read_nonblock(65536)
          rescue IO::WaitReadable
            next
          rescue EOFError, Errno::ECONNRESET, Errno::EPIPE
            return nil
          end
        end
        return [method, path, rest[0, content_length]]
      end
      nil
    end

    # 把任意字符串安全转成 UTF-8 并截断（防 JSON 生成时报编码/过长错误）
    def safe_json_str(s, limit = 2000)
      s = s.to_s.dup.force_encoding("UTF-8").scrub
      s.length > limit ? s[0, limit] : s
    end

    def respond(client, hash)
      safe = {}
      hash.each { |k, v| safe[k] = v.is_a?(String) ? safe_json_str(v) : v }
      json = JSON.generate(safe)
      client.write "HTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: #{json.bytesize}\r\nConnection: close\r\n\r\n#{json}"
    end
  end
end

begin
  Su.start_server
rescue Errno::EADDRINUSE
  puts "端口 #{Su::PORT} 被占用：服务可能已启动。若需重启请先执行 Su.stop_server 再重新 load。"
rescue Exception => e
  puts "启动失败: #{e.class}: #{e.message}"
end
