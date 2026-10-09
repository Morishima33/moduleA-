"""Git autocrlf 开启时，归档 CSV 的原始字节必须保持不变。"""
import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

class ArchiveCheckoutTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which("git"), "需要 Git 验证真实检出行为")
    def test_autocrlf_checkout_preserves_archived_bytes(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            source, checkout = root / "source", root / "checkout"
            source.mkdir()
            def git(*args, cwd=source):
                return subprocess.run(["git", "-c", "core.autocrlf=true", *args], cwd=cwd, check=True, capture_output=True)
            git("init", "--initial-branch=main")
            attrs = Path(__file__).resolve().parents[2] / ".gitattributes"
            shutil.copyfile(attrs, source / ".gitattributes")
            relative = Path("studies/study_fixture/runs/run_fixture/tables/components.csv")
            path = source / relative
            path.parent.mkdir(parents=True)
            content = "component,target\n示例,GENE1\n".encode("utf-8")
            path.write_bytes(content)
            git("add", ".")
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "fixture")
            git("clone", str(source), str(checkout), cwd=root)
            restored = (checkout / relative).read_bytes()
            self.assertEqual(restored, content)
            self.assertEqual(hashlib.sha256(restored).hexdigest(), hashlib.sha256(content).hexdigest())

if __name__ == "__main__":
    unittest.main()
