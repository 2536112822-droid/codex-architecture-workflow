"""Release adapter: extracted RhinoScript reference text is not bundled.

The upstream documentation tools remain registered and report this limitation.
Structured modeling tools do not depend on the documentation dataset.
"""


class _UnavailableDocumentation:
    def __iter__(self):
        raise RuntimeError(
            "RhinoScript reference documentation is not bundled in this release. "
            "Consult https://developer.rhino3d.com/api/RhinoScriptSyntax/ . "
            "Structured RhinoMCP modeling tools remain available."
        )


rhinoscriptsyntax_json = _UnavailableDocumentation()
