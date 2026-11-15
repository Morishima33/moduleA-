"""供Windows和macOS入口使用的Python引导；不依赖当前工作目录。"""
from pathlib import Path
import sys

if sys.version_info < (3, 11):
    raise SystemExit('需要Python 3.11或更新版本；请用MODULEA_PYTHON指定解释器')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from modulea.launcher import main
raise SystemExit(main())
