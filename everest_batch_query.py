#!/usr/bin/env python3
"""
Validity Everest API - CSV 批量域名查询工具
功能：
1. 读取 CSV 文件，自动识别域名列
2. 查询每个域名的子域名及其发信量
3. 查询每个域名使用的 ESP 竞品情报
4. 输出结果到新的 CSV 文件（横向多列格式）
5. 支持断点续传
"""

# ============== 依赖检测与自动安装 ==============
def check_and_install_dependencies():
    """
    检测所需库是否已安装，如果没有则自动安装
    支持多种安装方式，兼容不同系统环境
    """
    required_packages = {
        'requests': 'requests'  # {导入名: 包名}
    }

    missing_packages = []

    # 检测缺失的包
    for import_name, package_name in required_packages.items():
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(package_name)

    if not missing_packages:
        return True  # 所有依赖已安装

    print("=" * 50)
    print("检测到缺少以下依赖库，正在自动安装...")
    print(f"  缺少: {', '.join(missing_packages)}")
    print("=" * 50)

    # 尝试多种安装方式
    import subprocess
    import sys

    install_commands = [
        # 方式1: 使用当前 Python 解释器的 -m pip（最可靠）
        [sys.executable, '-m', 'pip', 'install', '--quiet'],
        # 方式2: 使用 pip3
        ['pip3', 'install', '--quiet'],
        # 方式3: 使用 pip
        ['pip', 'install', '--quiet'],
        # 方式4: 使用 python3 -m pip
        ['python3', '-m', 'pip', 'install', '--quiet'],
        # 方式5: 使用 python -m pip
        ['python', '-m', 'pip', 'install', '--quiet'],
    ]

    for package in missing_packages:
        installed = False

        for cmd_base in install_commands:
            try:
                cmd = cmd_base + [package]
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                if result.returncode == 0:
                    print(f"  ✓ 成功安装: {package}")
                    installed = True
                    break
            except FileNotFoundError:
                # 该命令不存在，尝试下一个
                continue
            except subprocess.TimeoutExpired:
                print(f"  警告: 安装 {package} 超时，尝试其他方式...")
                continue
            except Exception:
                continue

        if not installed:
            print(f"\n错误: 无法自动安装 {package}")
            print("\n请手动安装依赖库，可尝试以下命令：")
            print(f"  pip install {package}")
            print(f"  pip3 install {package}")
            print(f"  python -m pip install {package}")
            print(f"  python3 -m pip install {package}")
            print("\n如果没有 pip，请先安装 pip：")
            print("  macOS/Linux: curl https://bootstrap.pypa.io/get-pip.py | python3")
            print("  Windows: 下载 https://bootstrap.pypa.io/get-pip.py 后运行 python get-pip.py")
            return False

    print("\n所有依赖已安装完成！\n")
    return True


# 在导入其他库之前先检测依赖
if not check_and_install_dependencies():
    import sys
    sys.exit(1)

# ============== 正式导入 ==============
import csv
import getpass
import io
import json
import os
import re
import sys
import time
from datetime import datetime
from typing import Optional

import requests


# ============== 配置 ==============
API_BASE_URL = "https://api.everest.validity.com/api/2.0"
REQUEST_INTERVAL = 0.15  # 请求间隔（秒），500次/分钟 ≈ 每次0.12秒，留点余量
TIMEOUT = 30  # 请求超时时间（秒）
MAX_RETRIES = 3  # 最大重试次数
RETRY_DELAY = 0.5  # 重试等待时间（秒）
PROGRESS_FILE_SUFFIX = ".progress.json"  # 进度文件后缀
DEBUG_MODE = True  # 调试模式开关


def debug_print(msg: str):
    """调试输出"""
    if DEBUG_MODE:
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n  [{timestamp}] DEBUG: {msg}", flush=True)


# ============== 域名识别正则 ==============
# 匹配常见域名格式：example.com, sub.example.co.uk 等
DOMAIN_PATTERN = re.compile(
    r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
)


class EverestBatchQuery:
    """Everest API 批量查询类"""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {"X-API-KEY": api_key}
        self.request_count = 0
        self.last_request_time = 0

    def _rate_limit(self):
        """控制请求频率，避免触发 API 限速"""
        elapsed = time.time() - self.last_request_time
        if elapsed < REQUEST_INTERVAL:
            time.sleep(REQUEST_INTERVAL - elapsed)
        self.last_request_time = time.time()
        self.request_count += 1

    def _handle_error(self, response: requests.Response, context: str) -> str:
        """处理 HTTP 错误，返回错误信息"""
        status = response.status_code
        if status == 401:
            return "API_ERROR:401_无效或过期的API_Key"
        elif status == 403:
            return "API_ERROR:403_无权限"
        elif status == 429:
            return "API_ERROR:429_请求过于频繁"
        elif status == 404:
            return "API_ERROR:404_未找到"
        else:
            return f"API_ERROR:{status}_{context}"

    def step1_create_search(self, domain: str) -> dict:
        """
        第一步：发起域名搜索
        POST /api/2.0/prospect/search
        返回: {"success": True, "search_id": int, "matches": list} 或 {"success": False, "error": str}
        """
        debug_print(f"步骤1: POST 搜索域名 '{domain}'...")
        self._rate_limit()
        url = f"{API_BASE_URL}/prospect/search"

        # 使用 files 参数发送 multipart/form-data（与原脚本一致）
        files = {"domain": (None, domain)}

        try:
            debug_print(f"  → 发送请求到 {url}")
            response = requests.post(url, headers=self.headers, files=files, timeout=TIMEOUT)
            debug_print(f"  ← 响应状态码: {response.status_code}")

            if response.status_code != 200:
                debug_print(f"  ✗ 请求失败: {response.text[:100]}")
                return {"success": False, "error": self._handle_error(response, "创建搜索失败")}

            data = response.json()
            debug_print(f"  ← 响应数据: {str(data)[:200]}")
            results = data.get("results", {})

            # 处理 results 可能是字典或字符串的情况
            if isinstance(results, dict):
                search_id = results.get("id")
                matches = results.get("matches", [])
                debug_print(f"  ✓ 成功: search_id={search_id}, 匹配数={len(matches)}")
                return {
                    "success": True,
                    "search_id": search_id,
                    "matches": matches
                }
            else:
                # results 不是预期的字典格式
                debug_print(f"  ! results 非字典格式: {type(results)}")
                return {
                    "success": True,
                    "search_id": data.get("id"),
                    "matches": data.get("matches", [])
                }
        except requests.exceptions.RequestException as e:
            debug_print(f"  ✗ 请求异常: {str(e)}")
            return {"success": False, "error": f"REQUEST_ERROR:{str(e)[:50]}"}
        except json.JSONDecodeError:
            debug_print(f"  ✗ JSON 解析失败")
            return {"success": False, "error": "JSON_PARSE_ERROR"}

    def step2_confirm_matches(self, search_id: int, matches: str) -> dict:
        """
        第二步：确认匹配并获取发信量
        PUT /api/2.0/prospect/search/{id}
        返回: {"success": True, "volume": str, "traps": int} 或 {"success": False, "error": str}
        """
        debug_print(f"步骤2: PUT 确认匹配 search_id={search_id}, matches='{matches[:50]}...'")
        self._rate_limit()
        url = f"{API_BASE_URL}/prospect/search/{search_id}"
        data = {"matches": matches}

        try:
            debug_print(f"  → 发送请求到 {url}")
            response = requests.put(url, headers=self.headers, data=data, timeout=TIMEOUT)
            debug_print(f"  ← 响应状态码: {response.status_code}")

            if response.status_code != 200:
                debug_print(f"  ✗ 请求失败: {response.text[:100]}")
                return {"success": False, "error": self._handle_error(response, "确认匹配失败")}

            result_data = response.json()
            debug_print(f"  ← 响应数据: {str(result_data)[:200]}")
            results = result_data.get("results", {})

            # 处理 results 可能是字典或字符串的情况
            if isinstance(results, dict):
                volume = results.get("volume", "N/A")
                debug_print(f"  ✓ 成功: volume={volume}")
                return {
                    "success": True,
                    "volume": volume,
                    "traps": results.get("traps", 0),
                    "domain": results.get("domain", ""),
                    "search_id": search_id
                }
            else:
                # results 不是预期的字典格式，尝试从顶层获取
                debug_print(f"  ! results 非字典格式: {type(results)}")
                return {
                    "success": True,
                    "volume": result_data.get("volume", "N/A"),
                    "traps": result_data.get("traps", 0),
                    "domain": result_data.get("domain", ""),
                    "search_id": search_id
                }
        except requests.exceptions.RequestException as e:
            debug_print(f"  ✗ 请求异常: {str(e)}")
            return {"success": False, "error": f"REQUEST_ERROR:{str(e)[:50]}"}
        except json.JSONDecodeError:
            debug_print(f"  ✗ JSON 解析失败")
            return {"success": False, "error": "JSON_PARSE_ERROR"}

    def step3_get_esps(self, search_id: int) -> dict:
        """
        第三步：获取 ESP 竞品情报
        GET /api/2.0/prospect/search/{id}/esps
        返回: {"success": True, "esps": list} 或 {"success": False, "error": str}
        """
        debug_print(f"步骤3: GET ESP情报 search_id={search_id}")
        self._rate_limit()
        url = f"{API_BASE_URL}/prospect/search/{search_id}/esps"

        try:
            debug_print(f"  → 发送请求到 {url}")
            response = requests.get(url, headers=self.headers, timeout=TIMEOUT)
            debug_print(f"  ← 响应状态码: {response.status_code}")

            if response.status_code != 200:
                debug_print(f"  ✗ 请求失败: {response.text[:200]}")
                return {"success": False, "error": self._handle_error(response, "获取ESP失败")}

            data = response.json()
            debug_print(f"  ← ESP 完整响应: {json.dumps(data, ensure_ascii=False)[:500]}")

            # 尝试多种可能的数据结构
            results = data.get("results", data)

            # 提取 ESP 信息
            esps = []

            # 情况1: results 是字典，包含 esps 子键（实际API返回格式）
            # {"results": {"total": 759, "esps": {"SendGrid": 147, "MailChimp": 4, "Unknown": 608}}}
            if isinstance(results, dict):
                debug_print(f"  ESP results 是字典，键: {list(results.keys())}")

                esps_data = results.get("esps", {})
                total = results.get("total", 0)

                # esps 是字典格式: {"SendGrid": 147, "MailChimp": 4}
                if isinstance(esps_data, dict):
                    debug_print(f"  esps 是字典格式: {esps_data}")
                    for esp_name, count in esps_data.items():
                        # 计算百分比，保留两位小数确保精度
                        if total > 0 and count > 0:
                            percent = round(count / total * 100, 2)  # 保留两位小数
                        else:
                            percent = 0
                        esps.append({
                            "esp": esp_name,
                            "count": count,
                            "percent": percent
                        })
                        debug_print(f"    提取到 ESP: {esp_name} = {count} ({percent}%)")

                # esps 是列表格式
                elif isinstance(esps_data, list):
                    debug_print(f"  esps 是列表格式，长度: {len(esps_data)}")
                    for item in esps_data:
                        if isinstance(item, dict):
                            esp_name = item.get("esp") or item.get("name") or "Unknown"
                            esps.append({
                                "esp": esp_name,
                                "count": item.get("count", 0),
                                "percent": item.get("percent", 0)
                            })

            # 情况2: results 是列表
            elif isinstance(results, list):
                debug_print(f"  ESP results 是列表，长度: {len(results)}")
                for item in results:
                    if isinstance(item, dict):
                        esp_name = item.get("esp") or item.get("name") or "Unknown"
                        esps.append({
                            "esp": esp_name,
                            "count": item.get("count", 0),
                            "percent": item.get("percent", 0)
                        })

            # 按数量排序（降序）
            esps.sort(key=lambda x: x.get("count", 0), reverse=True)

            debug_print(f"  ✓ 成功: 获取到 {len(esps)} 个 ESP: {esps}")
            return {"success": True, "esps": esps}

        except requests.exceptions.RequestException as e:
            debug_print(f"  ✗ 请求异常: {str(e)}")
            return {"success": False, "error": f"REQUEST_ERROR:{str(e)[:50]}"}
        except json.JSONDecodeError as e:
            debug_print(f"  ✗ JSON 解析失败: {str(e)}")
            return {"success": False, "error": "JSON_PARSE_ERROR"}

    def _extract_domain_name(self, match_item) -> str:
        """从 matches 中提取域名字符串"""
        if isinstance(match_item, str):
            return match_item
        elif isinstance(match_item, dict):
            return match_item.get("domain") or match_item.get("name") or str(match_item)
        return str(match_item)

    def query_domain_full(self, domain: str) -> dict:
        """
        完整查询单个域名：子域名列表 + ESP情报 + 聚合发信量
        采用聚合查询模式：只查一次，得到所有子域名的聚合发信量
        如果结果异常（volume为空或N/A），会等待后重试
        返回: {
            "success": True,
            "subdomains": ["domain1", "domain2", ...],  # 子域名列表
            "volume": "聚合发信量",
            "esps": [{"esp": str, "percent": int}, ...]
        }
        """
        debug_print(f"========== 开始查询域名: {domain} ==========")

        # 带重试的查询逻辑
        for attempt in range(MAX_RETRIES):
            if attempt > 0:
                debug_print(f"第 {attempt + 1} 次重试，等待 {RETRY_DELAY} 秒...")
                time.sleep(RETRY_DELAY)

            result = self._query_domain_once(domain)

            # 检查结果是否有效
            if result["success"]:
                volume = result.get("volume", "")
                # 如果 volume 有效（非空、非N/A），直接返回
                if volume and volume != "N/A" and volume.strip() != "":
                    debug_print(f"========== 域名 {domain} 查询完成 ==========")
                    debug_print(f"  ESP数: {len(result['esps'])}, 子域名数: {len(result['subdomains'])}, 聚合发信量: {result['volume']}")
                    return result
                else:
                    # volume 无效，但有子域名，可能是频率限制导致
                    if result.get("subdomains"):
                        debug_print(f"警告: volume 为空或 N/A，可能是频率限制，准备重试...")
                        continue
                    else:
                        # 没有子域名，可能是域名本身没有数据
                        debug_print(f"========== 域名 {domain} 查询完成（无发信数据）==========")
                        return result
            else:
                # 查询失败，检查是否是可重试的错误
                error = result.get("error", "")
                if "429" in str(error) or "REQUEST_ERROR" in str(error):
                    debug_print(f"请求错误，准备重试: {error}")
                    continue
                else:
                    # 不可重试的错误，直接返回
                    debug_print(f"========== 域名 {domain} 查询失败: {error} ==========")
                    return result

        # 重试用尽，返回最后一次结果
        debug_print(f"========== 域名 {domain} 重试次数用尽 ==========")
        return result

    def _query_domain_once(self, domain: str) -> dict:
        """
        单次查询域名（不含重试逻辑）
        """
        result = {
            "success": False,
            "subdomains": [],
            "volume": "N/A",
            "esps": [],
            "error": None
        }

        # 步骤1：搜索主域名
        search_result = self.step1_create_search(domain)
        if not search_result["success"]:
            debug_print(f"步骤1失败: {search_result['error']}")
            result["error"] = search_result["error"]
            return result

        search_id = search_result["search_id"]
        matches = search_result["matches"]

        if not search_id:
            debug_print("错误: 未获取到 search_id")
            result["error"] = "NO_SEARCH_ID"
            return result

        # 提取所有匹配的域名
        subdomain_list = [self._extract_domain_name(m) for m in matches]
        debug_print(f"匹配到 {len(subdomain_list)} 个子域名: {subdomain_list}")

        if not subdomain_list:
            debug_print("错误: 没有匹配的域名")
            result["error"] = "NO_MATCHES_FOUND"
            return result

        # 保存子域名列表
        result["subdomains"] = subdomain_list

        # 步骤2：确认所有匹配，获取聚合发信量（只查一次）
        all_matches = ",".join(subdomain_list)
        confirm_result = self.step2_confirm_matches(search_id, all_matches)
        if not confirm_result["success"]:
            debug_print(f"步骤2失败: {confirm_result['error']}")
            result["error"] = confirm_result["error"]
            return result

        # 获取聚合发信量
        result["volume"] = confirm_result.get("volume", "N/A")
        debug_print(f"聚合发信量: {result['volume']}")

        # 步骤3：获取 ESP 情报
        esp_result = self.step3_get_esps(search_id)
        if esp_result["success"]:
            result["esps"] = esp_result["esps"]
        else:
            debug_print(f"步骤3失败（非致命）: {esp_result.get('error')}")

        result["success"] = True
        return result


def detect_domain_column(headers: list, sample_rows: list) -> Optional[int]:
    """
    自动检测 CSV 中的域名列
    返回列索引，如果找不到返回 None
    """
    # 首先检查列名是否包含域名相关关键词
    domain_keywords = ['domain', 'url', '域名', 'website', 'site', 'host']
    for i, header in enumerate(headers):
        header_lower = header.lower().strip()
        for keyword in domain_keywords:
            if keyword in header_lower:
                return i

    # 如果列名没有线索，检查数据内容
    for col_idx in range(len(headers)):
        domain_count = 0
        for row in sample_rows[:10]:  # 检查前10行
            if col_idx < len(row):
                value = row[col_idx].strip()
                if DOMAIN_PATTERN.match(value):
                    domain_count += 1
        # 如果超过一半的行匹配域名格式，认为是域名列
        if domain_count >= len(sample_rows[:10]) * 0.5:
            return col_idx

    return None


def load_progress(progress_file: str) -> dict:
    """加载进度文件"""
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"processed_rows": [], "results": {}}


def save_progress(progress_file: str, progress: dict):
    """保存进度文件"""
    with open(progress_file, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def format_output_row(original_row: list, query_result: dict) -> list:
    """
    格式化输出行 - 合并单列模式
    ESP 和子域名都用分号分隔合并到单列
    """
    new_row = list(original_row)

    debug_print(f"格式化输出行，query_result: {query_result}")

    # 检查是否有错误
    error = query_result.get("error")
    if error:
        debug_print(f"  查询有错误: {error}")
        new_row.append(f"ERROR: {error}")  # ESP
        new_row.append("")  # ESP占比
        new_row.append("")  # 存在发信的域名
        new_row.append("")  # 发信量估计
        return new_row

    # ESP 列：合并为 "ESP1; ESP2; ESP3"
    esps = query_result.get("esps", [])
    debug_print(f"  ESPs 原始数据: {esps}")
    esp_names = []
    esp_percents = []
    for item in esps:
        if isinstance(item, dict):
            esp_name = item.get("esp", "")
            esp_percent = item.get("percent", 0)
            if esp_name:  # 保留所有 ESP（包括 Unknown）
                esp_names.append(esp_name)
                # 格式化百分比：整数不显示小数，小数保留原精度
                if isinstance(esp_percent, float) and esp_percent != int(esp_percent):
                    esp_percents.append(f"{esp_percent}%")
                else:
                    esp_percents.append(f"{int(esp_percent)}%")
        elif isinstance(item, str):
            esp_names.append(item)
            esp_percents.append("N/A")

    new_row.append("; ".join(esp_names) if esp_names else "无ESP数据")
    new_row.append("; ".join(esp_percents) if esp_percents else "")

    # 存在发信的域名列：合并为 "domain1; domain2; domain3"
    subdomains = query_result.get("subdomains", [])
    debug_print(f"  Subdomains 原始数据: {subdomains}")
    if isinstance(subdomains, list) and len(subdomains) > 0:
        # 确保是字符串列表
        subdomain_strs = []
        for s in subdomains:
            if isinstance(s, str):
                subdomain_strs.append(s)
            elif isinstance(s, dict):
                subdomain_strs.append(s.get("domain", str(s)))
            else:
                subdomain_strs.append(str(s))
        new_row.append("; ".join(subdomain_strs))
    else:
        new_row.append("无匹配域名")

    # 发信量估计列：聚合发信量（单个值）
    volume = query_result.get("volume", "N/A")
    debug_print(f"  Volume: {volume}")
    new_row.append(volume if volume else "N/A")

    return new_row


def generate_output_headers(original_headers: list) -> list:
    """
    生成输出文件的表头 - 合并单列模式
    固定4列：ESP、ESP占比、存在发信的域名、发信量估计
    """
    new_headers = list(original_headers)
    new_headers.append("ESP")
    new_headers.append("ESP占比")
    new_headers.append("存在发信的域名")
    new_headers.append("发信量估计")
    return new_headers


def get_api_key() -> str:
    """安全地获取 API Key"""
    print("\n" + "=" * 60)
    print("Validity Everest API - CSV 批量域名查询工具")
    print("=" * 60)

    # Windows 上 getpass 不支持 Ctrl+V 粘贴，需要特殊处理
    if sys.platform == 'win32':
        print("\n提示: Windows 用户请直接粘贴 API Key（输入时会显示）")
        print("      或使用右键粘贴（而非 Ctrl+V）")
        api_key = input("请输入您的 API Key: ")
    else:
        api_key = getpass.getpass("\n请输入您的 API Key (输入时不会显示): ")

    # 清理 API Key：去除所有不可见字符、BOM、零宽空格等
    # 只保留 ASCII 可打印字符（API Key 通常只包含字母数字和少量符号）
    api_key = api_key.strip()
    # 移除 BOM 和其他不可见字符
    api_key = api_key.replace('\ufeff', '')  # BOM
    api_key = api_key.replace('\u200b', '')  # 零宽空格
    api_key = api_key.replace('\r', '').replace('\n', '')  # 换行符
    # 只保留可打印 ASCII 字符
    api_key = ''.join(c for c in api_key if 32 <= ord(c) < 127)

    if not api_key:
        print("错误: API Key 不能为空")
        sys.exit(1)

    debug_print(f"API Key 长度: {len(api_key)}, 前4位: {api_key[:4]}...")
    return api_key


def get_csv_file() -> str:
    """获取 CSV 文件路径"""
    file_path = input("\n请输入 CSV 文件路径: ").strip()
    if not file_path:
        print("错误: 文件路径不能为空")
        sys.exit(1)
    if not os.path.exists(file_path):
        print(f"错误: 文件不存在: {file_path}")
        sys.exit(1)
    return file_path


def main():
    """主程序入口"""
    try:
        # 1. 获取用户输入
        api_key = get_api_key()
        csv_file = get_csv_file()

        # 2. 读取 CSV 文件（自动检测编码：优先 UTF-8，回退 GBK）
        print(f"\n正在读取文件: {csv_file}")

        # 尝试多种编码
        encodings_to_try = ['utf-8-sig', 'utf-8', 'gbk', 'gb2312', 'gb18030', 'latin-1']
        file_content = None
        used_encoding = None

        for encoding in encodings_to_try:
            try:
                with open(csv_file, 'r', encoding=encoding) as f:
                    file_content = f.read()
                    used_encoding = encoding
                    debug_print(f"成功使用 {encoding} 编码读取文件")
                    break
            except UnicodeDecodeError:
                debug_print(f"编码 {encoding} 失败，尝试下一个...")
                continue

        if file_content is None:
            print("错误: 无法识别文件编码，请将文件另存为 UTF-8 格式")
            sys.exit(1)

        # 解析 CSV
        reader = csv.reader(io.StringIO(file_content))
        headers = next(reader)
        rows = list(reader)

        print(f"  共 {len(rows)} 行数据")
        print(f"  列名: {headers}")

        # 3. 检测域名列
        domain_col = detect_domain_column(headers, rows)
        if domain_col is None:
            print("\n未能自动检测到域名列，请手动指定:")
            for i, h in enumerate(headers):
                print(f"  [{i}] {h}")
            col_input = input("\n请输入域名列的编号: ").strip()
            try:
                domain_col = int(col_input)
            except ValueError:
                print("错误: 无效的列编号")
                sys.exit(1)
        else:
            print(f"\n自动检测到域名列: [{domain_col}] {headers[domain_col]}")
            confirm = input("确认使用此列? (Y/n): ").strip().lower()
            if confirm == 'n':
                for i, h in enumerate(headers):
                    print(f"  [{i}] {h}")
                col_input = input("\n请输入域名列的编号: ").strip()
                try:
                    domain_col = int(col_input)
                except ValueError:
                    print("错误: 无效的列编号")
                    sys.exit(1)

        # 4. 初始化 API 客户端
        client = EverestBatchQuery(api_key)

        # 5. 加载进度（断点续传）
        progress_file = csv_file + PROGRESS_FILE_SUFFIX
        progress = load_progress(progress_file)
        processed_rows = set(progress.get("processed_rows", []))
        results = progress.get("results", {})

        print(f"\n已处理 {len(processed_rows)} 行，继续处理剩余行...")

        # 6. 开始批量查询
        total_rows = len(rows)

        for row_idx, row in enumerate(rows):
            row_key = str(row_idx)

            # 跳过已处理的行
            if row_key in processed_rows:
                continue

            # 获取域名
            if domain_col >= len(row):
                results[row_key] = {"error": "COLUMN_INDEX_ERROR", "esps": [], "subdomains": [], "volume": "N/A"}
                processed_rows.add(row_key)
                continue

            domain = row[domain_col].strip()
            if not domain or not DOMAIN_PATTERN.match(domain):
                results[row_key] = {"error": "INVALID_DOMAIN", "esps": [], "subdomains": [], "volume": "N/A"}
                processed_rows.add(row_key)
                continue

            # 显示进度
            progress_pct = (row_idx + 1) / total_rows * 100
            print(f"\r[{progress_pct:5.1f}%] 正在查询 ({row_idx + 1}/{total_rows}): {domain}...", end="", flush=True)

            # 执行查询
            query_result = client.query_domain_full(domain)
            results[row_key] = query_result

            # 保存进度
            processed_rows.add(row_key)
            progress["processed_rows"] = list(processed_rows)
            progress["results"] = results
            save_progress(progress_file, progress)

        print(f"\n\n查询完成！共发起 {client.request_count} 次 API 请求")

        # 7. 生成输出文件（合并单列模式，固定4列）
        output_file = csv_file.rsplit('.', 1)[0] + "_result.csv"
        output_headers = generate_output_headers(headers)

        print(f"\n正在生成输出文件: {output_file}")

        with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(output_headers)

            for row_idx, row in enumerate(rows):
                row_key = str(row_idx)
                query_result = results.get(row_key, {"esps": [], "subdomains": [], "volume": "N/A"})
                output_row = format_output_row(row, query_result)
                writer.writerow(output_row)

        print(f"\n" + "=" * 60)
        print("处理完成!")
        print("=" * 60)
        print(f"  输入文件: {csv_file}")
        print(f"  输出文件: {output_file}")
        print(f"  处理行数: {len(rows)}")
        print(f"  新增列: ESP, ESP占比, 存在发信的域名, 发信量估计")
        print(f"  API 请求数: {client.request_count}")

        # 8. 删除进度文件
        if os.path.exists(progress_file):
            os.remove(progress_file)
            print(f"\n已清理进度文件")

    except KeyboardInterrupt:
        print("\n\n操作已取消（进度已保存，下次运行可继续）")
        sys.exit(0)
    except Exception as e:
        print(f"\n发生错误: {e}")
        print("进度已保存，修复问题后可继续运行")
        sys.exit(1)


if __name__ == "__main__":
    main()
