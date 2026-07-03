import subprocess
import sys

# 定义脚本路径
script_path = r"D:\new_tdx_mock\PYPlugins\user\tdxtest1.py"

# 调用并执行脚本
try:
    result = subprocess.run([sys.executable, script_path], capture_output=True, text=True, check=True)
    print("脚本输出:")
    print(result.stdout)
except subprocess.CalledProcessError as e:
    print(f"脚本执行失败，返回码: {e.returncode}")
    print(f"错误输出: {e.stderr}")
except FileNotFoundError:
    print(f"找不到脚本文件: {script_path}")
except Exception as e:
    print(f"执行过程中发生错误: {e}")
