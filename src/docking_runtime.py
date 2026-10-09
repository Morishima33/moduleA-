# A06内部依赖检查；由隔离的Python子进程调用，不替代网页入口。
import sys  # 检查解释器隔离标记。
import json  # 读取固定依赖清单。
import importlib  # 逐项导入实际工具。
import importlib.metadata  # 获取安装版本。
from pathlib import Path  # 校验工具实际位置。


def activate(root):  # 防止误用本机其他项目的科学依赖。
    if not (sys.flags.isolated and sys.flags.no_site):  # 同时屏蔽环境路径和全局site-packages。
        raise RuntimeError('A06结构工作进程必须使用Python -I -S启动')  # 不静默降级。
    root = Path(root).resolve()  # 明确新项目根。
    packages = root / 'environments' / 'docking_packages'  # 固定专用依赖目录。
    config = json.loads((root / 'environments' / 'A06_python_runtime.json').read_text(encoding='utf-8'))  # 不从网络猜版本。
    if config.get('schema_version') != 'A06.runtime.1':  # 只使用已实现格式。
        raise RuntimeError('A06依赖清单版本不支持')  # 拒绝未知结构。
    sys.path.insert(0,str(packages))  # 专用工具优先，并且没有全局site路径。
    checks = []  # 汇总实际版本和位置。
    for name, specification in config['packages'].items():  # 全部固定依赖都必须存在。
        version = importlib.metadata.version(name)  # 读取实际发行版版本。
        module = importlib.import_module(specification['module'])  # 确认不仅元数据存在。
        origin = Path(module.__file__).resolve()  # 确认加载的是本项目工具。
        if version != specification['version'] or not origin.is_relative_to(packages):  # 错版本或外部依赖都阻断。
            raise RuntimeError('A06依赖版本或位置不符：' + name)  # 不继续科学处理。
        checks.append({'package':name,'version':version,'path':origin.relative_to(root).as_posix()})  # 保存可迁移相对路径。
    return {'isolated':True,'global_site_disabled':True,'python_version':sys.version,'packages':checks}  # 此检查不是对接结果。


if __name__ == '__main__':  # 内部环境自检入口。
    project = Path(__file__).resolve().parents[1]  # 不依赖调用方当前目录。
    print(json.dumps(activate(project),ensure_ascii=False))  # 输出实际检查结果供上层归档。