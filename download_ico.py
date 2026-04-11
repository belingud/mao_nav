#!/usr/bin/env -S uv run --script
#
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "beautifulsoup4", "Pillow", "colorlog", "socksio", "cairosvg"]
# ///

# -*- coding: utf-8 -*-
"""
下载 mock_data.js 中所有 HTTP 图标到 public/sitelogo 目录。
"""

from __future__ import annotations

import io
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

import cairosvg
import colorlog
import httpx
from bs4 import BeautifulSoup
from PIL import Image


handler = colorlog.StreamHandler()
handler.setFormatter(
    colorlog.ColoredFormatter(
        "%(log_color)s[%(levelname)s]%(reset)s %(asctime)s - %(filename)s:%(lineno)d: %(message)s",
        datefmt="%H:%M:%S",
    )
)

logger = colorlog.getLogger("download_ico")
logger.setLevel(colorlog.INFO)
logger.propagate = False
if not logger.handlers:
    logger.addHandler(handler)


class FailureReason(Enum):
    ICON_NOT_FOUND = auto()
    NETWORK_ERROR = auto()
    CONVERSION_ERROR = auto()
    SAVE_ERROR = auto()


@dataclass(frozen=True)
class IconConfig:
    """图标下载流程配置。"""

    mock_data_file: Path = Path("src/mock/mock_data.js")
    output_dir: Path = Path("public/sitelogo")
    request_timeout: int = 10
    min_icon_size: int = 100
    headers: dict[str, str] = field(
        default_factory=lambda: {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        }
    )
    icon_content_types: tuple[str, ...] = ("image/x-icon", "image/vnd.microsoft.icon")
    png_content_types: tuple[str, ...] = ("image/png",)
    svg_content_types: tuple[str, ...] = ("image/svg+xml",)
    favicon_rels: tuple[str, ...] = ("icon", "shortcut icon", "apple-touch-icon")
    common_svg_paths: tuple[str, ...] = (
        "/logo.svg",
        "/assets/logo.svg",
        "/images/logo.svg",
        "/img/logo.svg",
        "/brand/logo.svg",
    )


@dataclass(frozen=True)
class IconInfo:
    """导航站点图标描述。"""

    site_name: str
    site_url: str
    filename: str

    def output_path(self, output_dir: Path) -> Path:
        return output_dir / self.filename

    @classmethod
    def from_site(cls, site: dict[str, Any]) -> IconInfo | None:
        icon_path = str(site.get("icon", "")).strip()
        site_url = str(site.get("url", "")).strip()

        if not icon_path or not site_url.startswith("http"):
            return None

        parsed_icon_path = Path(urlparse(icon_path).path)
        if parsed_icon_path.parent.as_posix() == "/sitelogo" and parsed_icon_path.name:
            filename = f"{parsed_icon_path.stem}.ico"
        else:
            filename = f"{urlparse(site_url).netloc}.ico"

        return cls(
            site_name=str(site.get("name", "")).strip(),
            site_url=site_url,
            filename=filename,
        )


@dataclass(frozen=True)
class FetchedIcon:
    """从网络取回的原始图标数据。"""

    url: str
    content: bytes
    content_type: str


@dataclass(frozen=True)
class ResolveResult:
    icon: FetchedIcon | None = None
    reason: FailureReason | None = None
    strategy_name: str | None = None


@dataclass
class ResolutionContext:
    """单次解析站点图标时共享的上下文。"""

    site_url: str
    base_url: str
    session: httpx.Client
    config: IconConfig
    had_network_error: bool = False
    soup: BeautifulSoup | None = None
    html_fetched: bool = False


Strategy = Callable[[ResolutionContext], FetchedIcon | None]
NamedStrategy = tuple[str, Strategy]


def _matches(content_type: str, expected: tuple[str, ...]) -> bool:
    normalized = content_type.lower()
    return any(item in normalized for item in expected)


def is_ico(content_type: str, config: IconConfig) -> bool:
    return _matches(content_type, config.icon_content_types)


def is_png(content_type: str, config: IconConfig) -> bool:
    return _matches(content_type, config.png_content_types)


def is_svg(content_type: str, config: IconConfig) -> bool:
    return _matches(content_type, config.svg_content_types)


def is_supported(content_type: str, config: IconConfig) -> bool:
    return is_ico(content_type, config) or is_png(content_type, config) or is_svg(content_type, config)


def detect_content_type(content: bytes, declared_content_type: str) -> str:
    sniffed = _sniff_content_type(content)
    return sniffed or declared_content_type


def _sniff_content_type(content: bytes) -> str:
    if content.startswith(b"\x00\x00\x01\x00"):
        return "image/x-icon"

    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"

    lowered = content[:1024].lstrip().lower()
    if lowered.startswith(b"<?xml"):
        _, _, lowered = lowered.partition(b"?>")
        lowered = lowered.lstrip()

    if b"<svg" in lowered:
        return "image/svg+xml"

    return ""


def _normalize_rel(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [raw.strip().lower()]
    if isinstance(raw, list):
        return [str(value).strip().lower() for value in raw]
    return []


def _icon_size_score(raw_sizes: Any) -> int:
    if not isinstance(raw_sizes, str):
        return 0

    best = 0
    for token in raw_sizes.lower().split():
        if token == "any":
            return 4096

        match = re.fullmatch(r"(\d+)x(\d+)", token)
        if not match:
            continue

        width, height = (int(value) for value in match.groups())
        best = max(best, min(width, height))

    return best


def build_context(site_url: str, session: httpx.Client, config: IconConfig) -> ResolutionContext:
    parsed = urlparse(site_url)
    return ResolutionContext(
        site_url=site_url,
        base_url=f"{parsed.scheme}://{parsed.netloc}",
        session=session,
        config=config,
    )


def fetch_html(ctx: ResolutionContext) -> BeautifulSoup | None:
    if ctx.html_fetched:
        return ctx.soup

    try:
        response = ctx.session.get(
            ctx.site_url,
            headers=ctx.config.headers,
            timeout=ctx.config.request_timeout,
        )
        response.raise_for_status()
        ctx.soup = BeautifulSoup(response.text, "html.parser")
    except httpx.RequestError:
        ctx.had_network_error = True
        ctx.soup = None
    except httpx.HTTPStatusError:
        ctx.soup = None

    ctx.html_fetched = True
    return ctx.soup


def fetch_resource(
    ctx: ResolutionContext,
    url: str,
    *,
    validator: Callable[[str, IconConfig], bool],
    min_size: int = 0,
) -> FetchedIcon | None:
    try:
        response = ctx.session.get(
            url,
            headers=ctx.config.headers,
            timeout=ctx.config.request_timeout,
        )
    except httpx.RequestError:
        ctx.had_network_error = True
        return None

    if not response.is_success or len(response.content) < min_size:
        return None

    content_type = detect_content_type(
        response.content,
        response.headers.get("Content-Type", ""),
    )
    if not validator(content_type, ctx.config):
        return None

    return FetchedIcon(url=url, content=response.content, content_type=content_type)


def fetch_icon(ctx: ResolutionContext, url: str) -> FetchedIcon | None:
    return fetch_resource(
        ctx,
        url,
        validator=is_supported,
        min_size=ctx.config.min_icon_size,
    )


def fetch_svg(ctx: ResolutionContext, url: str) -> FetchedIcon | None:
    return fetch_resource(ctx, url, validator=is_svg)


def resolve_favicon(ctx: ResolutionContext) -> FetchedIcon | None:
    return fetch_icon(ctx, f"{ctx.base_url}/favicon.ico")


def resolve_link_tag(ctx: ResolutionContext) -> FetchedIcon | None:
    soup = fetch_html(ctx)
    if not soup:
        return None

    candidates: list[tuple[int, str]] = []
    for tag in soup.find_all("link", href=True):
        rel_values = _normalize_rel(tag.get("rel"))
        rel_text = " ".join(rel_values)
        if not any(rel == rel_text or rel in rel_values for rel in ctx.config.favicon_rels):
            continue

        href = urljoin(ctx.site_url, tag["href"])
        candidates.append((_icon_size_score(tag.get("sizes")), href))

    for _, href in sorted(candidates, key=lambda item: item[0], reverse=True):
        fetched = fetch_icon(ctx, href)
        if fetched:
            return fetched

    return None


def resolve_svg_logo(ctx: ResolutionContext) -> FetchedIcon | None:
    soup = fetch_html(ctx)
    if soup:
        for tag in soup.find_all(["img", "source"], limit=10):
            src = tag.get("src") or tag.get("data-src") or tag.get("href")
            if src and Path(urlparse(src).path).suffix.lower() == ".svg":
                fetched = fetch_svg(ctx, urljoin(ctx.site_url, src))
                if fetched:
                    return fetched

    for path in ctx.config.common_svg_paths:
        fetched = fetch_svg(ctx, f"{ctx.base_url}{path}")
        if fetched:
            return fetched

    return None


DEFAULT_STRATEGIES: tuple[NamedStrategy, ...] = (
    ("link_tag", resolve_link_tag),
    ("favicon", resolve_favicon),
    ("svg_logo", resolve_svg_logo),
)


def resolve_icon(
    site_url: str,
    session: httpx.Client,
    config: IconConfig,
    strategies: tuple[NamedStrategy, ...] | list[NamedStrategy] = DEFAULT_STRATEGIES,
) -> ResolveResult:
    ctx = build_context(site_url, session, config)

    for strategy_name, strategy in strategies:
        fetched = strategy(ctx)
        if fetched:
            return ResolveResult(icon=fetched, strategy_name=strategy_name)

    reason = FailureReason.NETWORK_ERROR if ctx.had_network_error else FailureReason.ICON_NOT_FOUND
    return ResolveResult(reason=reason)


def png_to_ico(png_data: bytes) -> bytes:
    try:
        image = Image.open(io.BytesIO(png_data))
        if image.mode != "RGBA":
            image = image.convert("RGBA")

        buffer = io.BytesIO()
        side = min(image.width, image.height)
        if side >= 32:
            image.save(buffer, format="ICO", sizes=[(32, 32)])
        else:
            image.save(buffer, format="ICO")
        return buffer.getvalue()
    except Exception as exc:
        logger.warning(f"PNG 转 ICO 失败: {exc}")
        return b""


def svg_to_ico(svg_data: bytes) -> bytes:
    try:
        png_data = cairosvg.svg2png(bytestring=svg_data, output_width=32, output_height=32)
        return png_to_ico(png_data)
    except Exception as exc:
        logger.warning(f"SVG 转 ICO 失败: {exc}")
        return b""


def convert_to_ico(fetched: FetchedIcon, config: IconConfig) -> bytes:
    if is_png(fetched.content_type, config):
        logger.info("ℹ️  检测到 PNG，转换为 ICO...")
        return png_to_ico(fetched.content)

    if is_svg(fetched.content_type, config):
        logger.info("ℹ️  检测到 SVG，转换为 ICO...")
        return svg_to_ico(fetched.content)

    return fetched.content


def load_mock_data(data_file: Path) -> dict[str, Any]:
    if not data_file.exists():
        raise FileNotFoundError(f"找不到文件: {data_file}")

    content = data_file.read_text(encoding="utf-8")
    match = re.search(r"export const mockData\s*=\s*({.*})\s*;?\s*$", content, re.DOTALL)
    if not match:
        raise ValueError("无法解析 mock_data.js 文件")

    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON 解析错误: {exc}") from exc


def list_http_icons(data_file: Path) -> list[IconInfo]:
    icons: list[IconInfo] = []

    for category in load_mock_data(data_file).get("categories", []):
        for site in category.get("sites", []):
            icon_info = IconInfo.from_site(site)
            if icon_info:
                icons.append(icon_info)

    return icons


def deduplicate_icons(icons: list[IconInfo]) -> list[IconInfo]:
    unique_icons: list[IconInfo] = []
    seen_filenames: set[str] = set()
    duplicate_count = 0

    for icon in icons:
        if icon.filename in seen_filenames:
            duplicate_count += 1
            continue

        seen_filenames.add(icon.filename)
        unique_icons.append(icon)

    if duplicate_count:
        logger.info(f"ℹ️  跳过重复输出文件名: {duplicate_count} 个")

    return unique_icons


def is_valid_existing_icon(path: Path) -> bool:
    try:
        if path.stat().st_size == 0:
            return False

        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, ValueError):
        return False


def filter_pending_icons(icons: list[IconInfo], output_dir: Path) -> list[IconInfo]:
    pending_icons: list[IconInfo] = []
    skipped_count = 0
    invalid_count = 0

    for icon in icons:
        output_path = icon.output_path(output_dir)
        if output_path.exists() and is_valid_existing_icon(output_path):
            skipped_count += 1
            continue
        if output_path.exists():
            invalid_count += 1
        pending_icons.append(icon)

    if skipped_count:
        logger.info(f"ℹ️  跳过已存在图标: {skipped_count} 个")

    if invalid_count:
        logger.info(f"ℹ️  检测到无效图标，将重新下载: {invalid_count} 个")

    return pending_icons


def build_client(config: IconConfig) -> httpx.Client:
    return httpx.Client(
        timeout=config.request_timeout,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
    )


def save_icon(icon_info: IconInfo, data: bytes, output_dir: Path) -> FailureReason | None:
    output_path = icon_info.output_path(output_dir)
    try:
        output_path.write_bytes(data)
        logger.info(f"✅ 下载成功: {icon_info.filename} ({output_path.stat().st_size} bytes)")
        return None
    except OSError as exc:
        logger.warning(f"❌ 保存失败: {icon_info.filename} - {exc}")
        return FailureReason.SAVE_ERROR


def download_icon(icon_info: IconInfo, session: httpx.Client, config: IconConfig) -> FailureReason | None:
    logger.info(f"📥 获取图标: {icon_info.site_name} ({icon_info.filename})")

    resolved = resolve_icon(icon_info.site_url, session, config)
    if not resolved.icon:
        reason = resolved.reason or FailureReason.ICON_NOT_FOUND
        if reason is FailureReason.NETWORK_ERROR:
            logger.warning(f"❌ 网络错误: {icon_info.site_url}")
        else:
            logger.warning(f"❌ 未找到图标: {icon_info.site_url}")
        return reason

    logger.info(f"ℹ️  命中策略: {resolved.strategy_name} -> {resolved.icon.url}")

    ico_data = convert_to_ico(resolved.icon, config)
    if not ico_data:
        return FailureReason.CONVERSION_ERROR

    return save_icon(icon_info, ico_data, config.output_dir)


def print_summary(
    success_count: int,
    failed_results: list[tuple[IconInfo, FailureReason]],
    failure_breakdown: Counter[FailureReason],
    output_dir: Path,
) -> None:
    logger.info("📊 下载完成!")
    logger.info(f"✅ 成功: {success_count}")
    logger.info(f"❌ 失败: {len(failed_results)}")

    if failure_breakdown:
        logger.info("📋 失败原因分布:")
        for reason, count in failure_breakdown.items():
            logger.info(f"  {reason.name}: {count} 个")

    if failed_results:
        logger.info("❌ 失败的站点:")
        for icon_info, reason in failed_results:
            logger.info(f"  - [{reason.name}] {icon_info.site_url}")

    logger.info(f"📁 文件保存在: {output_dir.absolute()}")


def run(config: IconConfig | None = None) -> None:
    config = config or IconConfig()

    logger.info("🚀 开始下载图标...")
    config.output_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"📁 输出目录: {config.output_dir.absolute()}")

    icons = deduplicate_icons(list_http_icons(config.mock_data_file))
    logger.info(f"🔍 找到 {len(icons)} 个 HTTP 图标")

    pending_icons = filter_pending_icons(icons, config.output_dir)
    if not pending_icons:
        logger.info("✅ 所有图标已存在，无需下载")
        return

    logger.info(f"📦 需要下载 {len(pending_icons)} 个图标\n")

    success_count = 0
    failure_breakdown: Counter[FailureReason] = Counter()
    failed_results: list[tuple[IconInfo, FailureReason]] = []

    with build_client(config) as session:
        for icon in pending_icons:
            reason = download_icon(icon, session, config)
            if reason is None:
                success_count += 1
                continue

            failure_breakdown[reason] += 1
            failed_results.append((icon, reason))

    print_summary(success_count, failed_results, failure_breakdown, config.output_dir)


def main() -> None:
    try:
        run()
    except KeyboardInterrupt:
        logger.info("\n❌ 用户中断下载")
        sys.exit(1)
    except Exception as exc:
        logger.error(f"\n❌ 程序错误: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
