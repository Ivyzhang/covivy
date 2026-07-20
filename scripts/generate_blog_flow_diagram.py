from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "docs" / "assets" / "covivy-flow.png"
FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"


def font(size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_PATH, size=size, index=index)


def centered(draw: ImageDraw.ImageDraw, box, text: str, text_font, fill: str) -> None:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=text_font)
    width = right - left
    height = bottom - top
    x = box[0] + (box[2] - box[0] - width) / 2
    y = box[1] + (box[3] - box[1] - height) / 2 - top
    draw.text((x, y), text, font=text_font, fill=fill)


def main() -> None:
    image = Image.new("RGB", (1600, 620), "#f7f9fc")
    draw = ImageDraw.Draw(image)
    title_font = font(40)
    subtitle_font = font(22)
    node_title_font = font(26)
    node_body_font = font(19)
    guard_title_font = font(21)
    guard_body_font = font(18)

    draw.text((90, 55), "一份覆盖率报告的 Covivy 旅程", font=title_font, fill="#172033")
    draw.text(
        (90, 112),
        "从测试结果出发，经过可靠处理，回到开发者正在 review 的地方",
        font=subtitle_font,
        fill="#596579",
    )

    nodes = [
        ((80, 220, 310, 380), "#e7f2ff", "#1677c8", "#124a75", "CI / Action", ("运行测试", "上传覆盖率报告")),
        ((380, 220, 610, 380), "#eaf8ef", "#238b57", "#17613d", "FastAPI", ("验证仓库 token", "保存并创建任务")),
        ((680, 220, 910, 380), "#fff4dc", "#c47a12", "#80500f", "PostgreSQL", ("报告与 PR 状态", "任务锁、重试、退避")),
        ((980, 220, 1210, 380), "#f4edff", "#7754b3", "#533784", "Worker + 语义引擎", ("解析 diff 与源码", "计算 patch coverage")),
        ((1280, 220, 1520, 380), "#ffecef", "#c74358", "#852b3a", "PR 反馈", ("Status + 稳定评论", "文件与行级 Dashboard")),
    ]

    for box, fill, outline, title_color, title, lines in nodes:
        draw.rounded_rectangle(box, radius=8, fill=fill, outline=outline, width=3)
        current_title_font = font(21) if title == "Worker + 语义引擎" else node_title_font
        centered(draw, (box[0], 245, box[2], 295), title, current_title_font, title_color)
        centered(draw, (box[0], 305, box[2], 335), lines[0], node_body_font, "#4d5c70")
        centered(draw, (box[0], 337, box[2], 367), lines[1], node_body_font, "#4d5c70")

    for start, end in ((320, 365), (620, 665), (920, 965), (1220, 1265)):
        draw.line((start, 300, end, 300), fill="#7a8699", width=5)
        draw.line((end - 14, 286, end, 300), fill="#7a8699", width=5)
        draw.line((end - 14, 314, end, 300), fill="#7a8699", width=5)

    guard = (350, 450, 1250, 542)
    draw.rounded_rectangle(guard, radius=8, fill="#ffffff", outline="#d5dce7", width=2)
    centered(draw, (350, 462, 1250, 497), "可靠性护栏", guard_title_font, "#263246")
    centered(
        draw,
        (350, 500, 1250, 532),
        "webhook / upload 乱序兼容 · force-push 旧报告隔离 · 路径歧义告警 · OAuth token 恢复",
        guard_body_font,
        "#5b6678",
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT, format="PNG", optimize=True)


if __name__ == "__main__":
    main()
