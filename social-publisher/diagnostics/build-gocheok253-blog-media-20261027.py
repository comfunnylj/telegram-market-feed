#!/usr/bin/env python3
"""Build verified, fact-labelled Gocheok253 redevelopment blog charts (not renderings).
Verified inputs: Seoul notice 2025-226; Jaegebal listing observed 2026-10-25;
individual apt transactions sourced as shown in Korean caption. No publication.
"""
from PIL import Image,ImageDraw,ImageFont
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[2]
DEST=ROOT/"social-publisher/media"
DEST.mkdir(parents=True,exist_ok=True)
FT="/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
FB="/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"
assert Path(FT).exists() and Path(FB).exists(),"Nanum font must be installed"
W,H=1600,1000
BG="#EDF2F9";NAVY="#14243F";MID="#233F6D";BLUE="#3168D4"
TEAL="#0D8D8D";INK="#14243F";FADE="#61738C";AMBER="#E59C38"
def font(n,b=False):return ImageFont.truetype(FB if b else FT,n)
def canvas(title,subtitle):
 im=Image.new("RGB",(W,H),BG);d=ImageDraw.Draw(im)
 d.rounded_rectangle((40,35,1560,965),radius=28,fill="#FFFFFF")
 d.rounded_rectangle((40,35,1560,186),radius=28,fill=NAVY)
 d.rectangle((40,130,1560,186),fill=NAVY)
 d.text((91,70),title,font=font(52,True),fill="#FFFFFF")
 d.text((91,212),subtitle,font=font(27),fill=FADE)
 return im,d
def txt(d,x,y,text,n=31,b=False,color=INK):
 d.text((x,y),text,font=font(n,b),fill=color)
def note(d,line1,line2=""):
 d.line((92,837,1508,837),fill="#D8E1ED",width=3)
 txt(d,95,851,line1,22,False,FADE)
 if line2:txt(d,95,891,line2,22,False,FADE)
def save(im,file):
 p=DEST/file
 im.save(p,"PNG",optimize=True)
 with Image.open(p) as verify: verify.verify()
 data=p.read_bytes()
 return {"name":file,"width":W,"height":H,"size":len(data),"sha256":hashlib.sha256(data).hexdigest()}

im,d=canvas("고척동 253 | 3억 매물의 초기투자금","2026년 10월 25일 확인한 재개발닷컴 공개 매도호가")
d.rounded_rectangle((94,293,751,548),radius=24,fill="#E8EFFC")
d.rounded_rectangle((793,293,1506,548),radius=24,fill="#E7F5F2")
txt(d,130,323,"매매 호가",34,True)
txt(d,829,323,"플랫폼 표시 초기투자금",33,True)
txt(d,130,398,"3억 원",90,True,BLUE)
txt(d,829,398,"1억 7,200만 원",67,True,TEAL)
txt(d,109,603,"호가와 초투 차이",32,True)
txt(d,455,590,"1억 2,800만 원",54,True,"#B96B1F")
txt(d,110,715,"매물 대지지분",30,True)
txt(d,475,706,"7.11평",49,True)
note(d,"※ 초투는 플랫폼 표시액이며 보증금·대출 등 차액 구성은 미확인","※ 취득세·거래비용·분양자격·추가분담금은 별도로 확인해야 함")
meta=[save(im,"gocheok253_03_entry_price.png")]

im,d=canvas("고척동 253 | 1,469세대 공급 구조","2025년 서울시 고시 / 일반분양 683세대는 플랫폼 단순 추정치")
txt(d,111,301,"전체 1,469세대",51,True,NAVY)
start=117
segments=[(1243,BLUE),(226,AMBER)]
for count,color in segments:
 width=round((1390*count)/1469)
 d.rectangle((start,395,start+width,500),fill=color)
 start+=width
txt(d,111,535,"분양주택 1,243세대",31,True,BLUE)
txt(d,1000,535,"임대 226세대",30,True,"#B96B1F")
d.rounded_rectangle((107,630,1490,797),radius=20,fill="#EAF5F5")
txt(d,142,653,"민간 플랫폼 표시 소유자 560명",34,True,NAVY)
txt(d,142,719,"일반분양 683세대 = 1,243 − 560 (확정값 아님)",29,True,TEAL)
note(d,"※ 분양대상자·보류지·분양신청 결과에 따라 실제 일반분양 달라질 수 있음","※ 공식 고시 추정비례율 111.79% 역시 2025년 사업수지 가정값")
meta.append(save(im,"gocheok253_04_supply_valuation.png"))

im,d=canvas("고척동 일대 84㎡형 개별 실거래","2026년 계약 사례 / 서로 다른 연식·층·방향을 비교한 참고자료")
items=[
 ("한일유앤아이","2026.10.09",7.48),
 ("동아한신","2026.09.30",7.90),
 ("벽산","2026.09.29",10.50),
 ("고척파크푸르지오","2026.04.08",11.30),
 ("삼환로즈빌","2026.09.23",11.50),
]
for i,(name,date,val) in enumerate(items):
 y=315+i*100
 txt(d,103,y,name,29,True)
 txt(d,108,y+39,date,20,False,FADE)
 bar=int(690*val/12)
 d.rounded_rectangle((560,y+9,560+bar,y+66),radius=10,fill=TEAL if i>=3 else BLUE)
 txt(d,584+bar,y+16,f"{val:.2f}억",29,True,NAVY)
note(d,"※ 동일 단지 평균시세나 대상지 미래 신축 분양가가 아닌 개별 실거래","※ 가격 검증 자료: apt.k9gle.com 및 고척파크푸르지오 개별 실거래")
meta.append(save(im,"gocheok253_05_apt_comparables.png"))

report=ROOT/"social-publisher/diagnostics/gocheok253-20261027-media-report.json"
report.write_text(json.dumps({"site":"고척동 253", "source_date":"2026-10-27", "images":meta},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps(meta,ensure_ascii=False,indent=2),flush=True)
