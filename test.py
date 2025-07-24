#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载 mock_data.js 中所有 HTTP 图标到 public/sitelogo 目录
"""

import os
import re
import json
import requests
import time
from urllib.parse import urlparse
from pathlib import Path
import sys
from bs4 import BeautifulSoup
from urllib.parse import urljoin


def extract_mock_data():
    """从 mock_data.js 文件中提取数据"""
    mock_file = "src/mock/mock_data.js"

    if not os.path.exists(mock_file):
        print(f"❌ 找不到文件: {mock_file}")
        return None

    with open(mock_file, "r", encoding="utf-8") as f:
        content = f.read()

    # 使用正则表达式提取 JSON 数据
    match = re.search(r"export const mockData = ({.*})", content, re.DOTALL)
    if not match:
        print("❌ 无法解析 mock_data.js 文件")
        return None

    try:
        # 解析 JSON 数据
        data_str = match.group(1)
        data = json.loads(data_str)
        return data
    except json.JSONDecodeError as e:
        print(f"❌ JSON 解析错误: {e}")
        return None


def get_all_http_icons(data):
    """获取所有 HTTP 地址的图标"""
    http_icons = []

    for category in data.get("categories", []):
        for site in category.get("sites", []):
            icon_url = site.get("url", "")
            if icon_url.startswith("http"):
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


def resolve_favicon_url(site_url, session):
    """
    尝试获取网站的 .ico 格式 favicon 地址。
    优先使用 /favicon.ico，如果不是 .ico 格式则解析 HTML。
    返回: icon_url 或 None
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    }

    parsed_url = urlparse(site_url)
    base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

    # Step 1: 尝试 /favicon.ico
    ico_url = f"{base_url}/favicon.ico"
    try:
        resp = session.get(ico_url, headers=headers, timeout=10)
        content_type = resp.headers.get("Content-Type", "")
        if (
            resp.ok
            and len(resp.content) >= 100
            and ("image/x-icon" in content_type or "image/vnd.microsoft.icon" in content_type)
        ):
            return ico_url
    except requests.RequestException:
        pass  # 忽略 favicon.ico 失败，进入下一步

    # Step 2: fallback 解析 HTML 中 <link rel=icon>
    try:
        html_resp = session.get(site_url, headers=headers, timeout=10)
        soup = BeautifulSoup(html_resp.text, "html.parser")

        for rel in ["icon", "shortcut icon", "apple-touch-icon"]:
            tag = soup.find("link", rel=rel)
            if tag and tag.get("href"):
                icon_url = urljoin(base_url, tag["href"])
                resp = session.get(icon_url, headers=headers, timeout=10)
                content_type = resp.headers.get("Content-Type", "")
                if (
                    resp.ok
                    and len(resp.content) >= 100
                    and ("image/x-icon" in content_type or "image/vnd.microsoft.icon" in content_type)
                ):
                    return icon_url
    except requests.RequestException:
        pass

    return None


def download_icon(icon_info, output_dir, session):
    """
    下载单个图标文件（只下载 .ico 格式）
    参数：
        icon_info: dict，包含 'url', 'filename', 'site_name'
        output_dir: pathlib.Path
        session: requests.Session 实例
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
            print(f"❌ 未找到有效的 .ico 图标: {site_url}")
            return False

        resp = session.get(icon_url, stream=True, timeout=10)
        resp.raise_for_status()

        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(1024):
                f.write(chunk)

        print(f"✅ 下载成功: {filename} ({len(resp.content)} bytes)")
        return True

    except requests.RequestException as e:
        print(f"❌ 下载失败: {filename} - {e}")
        return False
    except Exception as e:
        print(f"❌ 保存失败: {filename} - {e}")
        return False


def main():
    """主函数"""
    print("🚀 开始下载图标...")

    # 创建输出目录
    output_dir = Path("public/sitelogo")
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

    # 创建会话以复用连接
    session = requests.Session()
    session.mount("http://", requests.adapters.HTTPAdapter(max_retries=3))
    session.mount("https://", requests.adapters.HTTPAdapter(max_retries=3))

    # 下载图标
    success_count = 0
    failed_count = 0

    print(f"\n📦 开始下载 {len(http_icons)} 个图标...\n")
    failed_urls = []

    for i, icon_info in enumerate(http_icons, 1):
        print(f"[{i}/{len(http_icons)}] ", end="")

        if download_icon(icon_info, output_dir, session):
            success_count += 1
        else:
            failed_count += 1
            failed_urls.append(icon_info["url"])

    # 关闭会话
    session.close()

    # 输出结果
    print("\n📊 下载完成!")
    print(f"✅ 成功: {success_count}")
    print(f"❌ 失败: {failed_count}")
    if failed_urls:
        print("❌ 失败的 URL:")
        for url in failed_urls:
            print(f"  - {url}")
    print(f"📁 文件保存在: {output_dir.absolute()}")

    # 显示已下载的文件
    downloaded_files = list(output_dir.glob("*.ico"))
    if downloaded_files:
        print(f"\n📋 已下载的文件 ({len(downloaded_files)} 个):")
        for file in sorted(downloaded_files):
            size = file.stat().st_size
            print(f"  - {file.name} ({size} bytes)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n❌ 用户中断下载")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 程序错误: {e}")
        sys.exit(1)
