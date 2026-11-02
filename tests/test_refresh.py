import refresh


def test_really_about_requires_tool_and_feature():
    g = {"tool": "Unreal Engine", "name": "Blueprint basics"}
    assert not refresh._really_about(g, "guide", "Fallon Sherrock beats 'The Nuke' in darts final")
    assert refresh._really_about(g, "guide", "Unreal Engine 5.8 adds new Blueprint debugging tools")
    b = {"tool": "Substance 3D", "name": "Substance Painter baking mesh maps"}
    assert refresh._really_about(b, "guide", "Substance 3D Painter 12.2 fixes cage baking errors")
