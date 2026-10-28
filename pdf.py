"""Plain-text PDF. No extra library, so the factory laptop needs nothing new."""


def text_pdf(lines: list[str]) -> bytes:
    safe = []
    for line in lines:
        text = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in line)
        safe.append(text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)"))

    commands = ["BT", "/F1 11 Tf", "40 800 Td", "14 TL"]
    for i, line in enumerate(safe):
        if i:
            commands.append("T*")
        commands.append(f"({line}) Tj")
    commands.append("ET")
    stream = "\n".join(commands).encode("latin-1", "replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF"
    ).encode()
    return bytes(out)
