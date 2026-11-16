import agents

NOOP = '''diff --git a/backend/app/main.py b/backend/app/main.py
--- a/backend/app/main.py
+++ b/backend/app/main.py
@@ -1,3 +1,3 @@
-    """엔진 목록 (PR #17 병합됨)."""
+    """엔진 목록 (PR #61 반영)."""
-            "description": "높이맵 메시 생성 (기본)",
+            "description": "높이맵 메시 생성 (기본, 웹 PBR 지원)",
diff --git a/backend/tests/test_core.py b/backend/tests/test_core.py
--- a/backend/tests/test_core.py
+++ b/backend/tests/test_core.py
@@ -1,1 +1,3 @@
+def test_x():
+    assert "웹 PBR" in get()
'''

REAL = '''diff --git a/backend/app/x.py b/backend/app/x.py
--- a/backend/app/x.py
+++ b/backend/app/x.py
@@ -1,2 +1,3 @@
 def f(a):
-    return a
+    if a is None:
+        raise ValueError("a 가 없음")
+    return a
'''


def test_noop_pr_is_rejected():
    p = agents.substance_problems(NOOP)
    assert any("기능 변화 없음" in x for x in p) and any("PR 번호" in x for x in p)


def test_real_change_passes():
    assert agents.substance_problems(REAL) == []
