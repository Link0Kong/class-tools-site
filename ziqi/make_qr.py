import qrcode
from qrcode.constants import ERROR_CORRECT_H
from PIL import Image, ImageDraw, ImageFont

URL = "https://me.furina.fun/"
qr = qrcode.QRCode(error_correction=ERROR_CORRECT_H, box_size=18, border=2)
qr.add_data(URL); qr.make(fit=True)
qimg = qr.make_image(fill_color="#23302E", back_color="#FFFFFF").convert("RGB")
qimg.save("qr_me_furina.png")
print("qr png:", qimg.size)

W = qimg.size[0] + 160
H = qimg.size[1] + 300
c = Image.new("RGB", (W, H), "#F7F8F8")
c.paste(qimg, (80, 140))

d = ImageDraw.Draw(c)
def font(path, size):
    try: return ImageFont.truetype(path, size)
    except Exception: return ImageFont.load_default()

f_title = font("C:/Windows/Fonts/msyhbd.ttc", 46)
f_sub   = font("C:/Windows/Fonts/msyh.ttc", 30)
f_url   = font("C:/Windows/Fonts/msyhbd.ttc", 42)

def center(txt, f, y, fill):
    w = d.textlength(txt, font=f)
    d.text(((W - w) / 2, y), txt, font=f, fill=fill)

center("陈子麒 · 竞选团支部副书记", f_title, 46, "#23302E")
center("扫码看我的自我介绍", f_sub, 108, "#5A6A67")
center("me.furina.fun", f_url, qimg.size[1] + 186, "#4E9082")
c.save("qr_card.png")
print("card:", c.size)
