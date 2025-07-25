#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载 mock_data.js 中所有 HTTP 图标到 public/sitelogo 目录
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from PIL import Image
import io


# ==================== 常量配置 ====================
MOCK_DATA_FILE = "src/mock/mock_data.js"
OUTPUT_DIR = "public/sitelogo"
REQUEST_TIMEOUT = 10
MIN_ICON_SIZE = 100
MAX_RETRIES = 3

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
}

ICON_CONTENT_TYPES = ["image/x-icon", "image/vnd.microsoft.icon"]
PNG_CONTENT_TYPES = ["image/png"]
FAVICON_RELS = ["icon", "shortcut icon", "apple-touch-icon"]


# ==================== 数据处理模块 ====================
def extract_mock_data() -> Optional[Dict]:
    """从 mock_data.js 文件中提取数据"""
    if not os.path.exists(MOCK_DATA_FILE):
        print(f"❌ 找不到文件: {MOCK_DATA_FILE}")
        return None

    try:
        with open(MOCK_DATA_FILE, "r", encoding="utf-8") as f:
            content = f.read()

        # 使用正则表达式提取 JSON 数据
        match = re.search(r"export const mockData = ({.*})", content, re.DOTALL)
        if not match:
            print("❌ 无法解析 mock_data.js 文件")
            return None

        data_str = match.group(1)
        return json.loads(data_str)
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析错误: {e}")
        return None
    except Exception as e:
        print(f"❌ 读取文件错误: {e}")
        return None


def get_all_http_icons(data: Dict) -> List[Dict]:
    """获取所有 HTTP 地址的图标信息"""
    http_icons = []

    for category in data.get("categories", []):
        for site in category.get("sites", []):
            icon_url = site.get("url", "")
            if not icon_url.startswith("http"):
                continue

            # 提取域名作为文件名
            if "favicon/" in icon_url:
                # 从 icon.maodeyu.fun/favicon/domain 提取域名
                domain = icon_url.split("/favicon/")[-1]
            else:
                # 从普通URL提取域名
                parsed = urlparse(site.get("url", ""))
                domain = parsed.netloc

            http_icons.append(
                {
                    "url": icon_url,
                    "domain": domain,
                    "filename": f"{domain}.ico",
                    "site_name": site.get("name", ""),
                    "site_url": site.get("url", ""),
                }
            )

    return http_icons


# ==================== 图标获取模块 ====================
def convert_png_to_ico(png_data: bytes) -> bytes:
    """将PNG数据转换为ICO格式"""
    try:
        # 从字节数据创建PIL图像
        png_image = Image.open(io.BytesIO(png_data))
        
        # 转换为RGBA模式（支持透明度）
        if png_image.mode != 'RGBA':
            png_image = png_image.convert('RGBA')
        
        # 创建ICO格式的字节流
        ico_buffer = io.BytesIO()
        png_image.save(ico_buffer, format='ICO', sizes=[(32, 32)])
        ico_buffer.seek(0)
        
        return ico_buffer.getvalue()
    except Exception as e:
        print(f"❌ PNG转ICO失败: {e}")
        return b""
def _is_valid_icon_response(response: httpx.Response) -> bool:
    """检查响应是否为有效的图标文件（ICO或PNG）"""
    if not response.is_success or len(response.content) < MIN_ICON_SIZE:
        return False

    content_type = response.headers.get("Content-Type", "")
    # 支持ICO和PNG格式
    return (any(ico_type in content_type for ico_type in ICON_CONTENT_TYPES) or 
            any(png_type in content_type for png_type in PNG_CONTENT_TYPES))


def _try_favicon_ico(base_url: str, session: httpx.Client) -> Optional[str]:
    """尝试获取 /favicon.ico"""
    ico_url = f"{base_url}/favicon.ico"
    try:
        resp = session.get(ico_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if _is_valid_icon_response(resp):
            return ico_url
    except httpx.RequestError:
        pass
    return None


def _try_html_favicon(site_url: str, base_url: str, session: httpx.Client) -> Optional[str]:
    """从 HTML 中解析 favicon 链接"""
    try:
        html_resp = session.get(site_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        soup = BeautifulSoup(html_resp.text, "html.parser")

        for rel in FAVICON_RELS:
            tag = soup.find("link", rel=rel)
            if tag and tag.get("href"):
                icon_url = urljoin(base_url, tag["href"])
                resp = session.get(icon_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
                if _is_valid_icon_response(resp):
                    return icon_url
    except httpx.RequestError:
        pass
    return None


def resolve_favicon_url(site_url: str, session: httpx.Client) -> Optional[str]:
    """
    尝试获取网站的图标地址（ICO 或 PNG）
    优先使用 /favicon.ico，如果找不到或无效，则解析 HTML
    """
    parsed_url = urlparse(site_url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

    # 优先尝试 /favicon.ico
    icon_url = _try_favicon_ico(base_url, session)
    if icon_url:
        return icon_url

    # 回退到解析 HTML
    return _try_html_favicon(site_url, base_url, session)


# ==================== 下载模块 ====================
def download_icon(icon_info: Dict, output_dir: Path, session: httpx.Client) -> bool:
    """
    下载单个图标文件，如果是PNG则转换为ICO格式
    """
    site_url = icon_info["url"]
    filename = icon_info["filename"]
    filepath = output_dir / filename

    if filepath.exists():
        print(f"⏭️  跳过已存在的文件: {filename}")
        return True

    print(f"📥 获取图标: {icon_info['site_name']} ({filename})")

    try:
        icon_url = resolve_favicon_url(site_url, session)
        if not icon_url:
            print(f"❌ 未找到有效的图标: {site_url}")
            return False

        resp = session.get(icon_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        icon_data = resp.content

        # 如果是PNG，则转换为ICO
        if any(png_type in content_type for png_type in PNG_CONTENT_TYPES):
            print("ℹ️  检测到PNG格式，正在转换为ICO...")
            icon_data = convert_png_to_ico(icon_data)
            if not icon_data:
                return False

        with open(filepath, "wb") as f:
            f.write(icon_data)

        print(f"✅ 下载成功: {filename} ({filepath.stat().st_size} bytes)")
        return True

    except httpx.RequestError as e:
        print(f"❌ 下载失败: {filename} - {e}")
        return False
    except Exception as e:
        print(f"❌ 保存失败: {filename} - {e}")
        return False


def _create_client() -> httpx.Client:
    """创建配置好的 httpx 客户端"""
    return httpx.Client(
        timeout=REQUEST_TIMEOUT,
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    )


def _print_download_summary(
    success_count: int, failed_count: int, failed_urls: List[str], output_dir: Path
) -> None:
    """打印下载结果摘要"""
    print("\n📊 下载完成!")
    print(f"✅ 成功: {success_count}")
    print(f"❌ 失败: {failed_count}")

    if failed_urls:
        print("❌ 失败的 URL:")
        for url in failed_urls:
            print(f"  - {url}")

    print(f"📁 文件保存在: {output_dir.absolute()}")


# ==================== 主程序模块 ====================
def main() -> None:
    """主函数"""
    print("🚀 开始下载图标...")

    # 创建输出目录
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"📁 输出目录: {output_dir.absolute()}")

    # 提取数据
    print("📖 读取 mock_data.js...")
    data = extract_mock_data()
    if not data:
        return

    # 获取所有HTTP图标
    http_icons = get_all_http_icons(data)
    print(f"🔍 找到 {len(http_icons)} 个 HTTP 图标")

    if not http_icons:
        print("✅ 没有需要下载的图标")
        return

    # 创建客户端并下载图标
    success_count = 0
    failed_count = 0
    failed_urls = []

    print(f"\n📦 开始下载 {len(http_icons)} 个图标...\n")

    with _create_client() as client:
        for i, icon_info in enumerate(http_icons, 1):
            print(f"[{i}/{len(http_icons)}] ", end="")

            if download_icon(icon_info, output_dir, client):
                success_count += 1
            else:
                failed_count += 1
                failed_urls.append(icon_info["url"])

    # 输出结果摘要
    _print_download_summary(success_count, failed_count, failed_urls, output_dir)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n❌ 用户中断下载")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 程序错误: {e}")
        sys.exit(1)
