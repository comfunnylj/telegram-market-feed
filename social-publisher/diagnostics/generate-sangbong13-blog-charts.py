#!/usr/bin/env python3
"""Generate original, factual Sangbong13 blog chart images (no blog/social publication)."""
from pathlib import Path
import os
from PIL import Image,ImageDraw,ImageFont

OUT=Path("social-publisher/media")
OUT.mkdir(parents=True,exist_ok=True)
F="/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
FB="/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"
assert Path(F).exists(), "Korean font package is required"
def font(sz,bold=False):return ImageFont.truetype(FB if bold else F,sz)
BG="#f8f9fc"; NAVY="#172e48"; GREY="#546477"; BLUE="#2779ad"; TEAL="#159c95"; ORANGE="#c77b39"; LIGHT="#e8eef4"; WHITE="#ffffff"
W,H=1440,900
def canvas(title,subtitle):
 im=Image.new("RGB",(W,H),BG);d=ImageDraw.Draw(im)
 d.rounded_rectangle((44,40,W-44,H-38),radius=35,fill=WHITE)
 d.rectangle((44,40,61,H-38),fill=BLUE)
 d.text((98,92),title,font=font(59,True),fill=NAVY)
 d.text((98,178),subtitle,font=font(28),fill=GREY)
 d.line((95,244,1350,244),fill=LIGHT,width=3)
 return im,d
def smalltext(d,text,y):
 d.text((99,y),text,font=font(25),fill=GREY)
def chart1():
 im,d=canvas("상봉13구역 · 공개 매물 진입가격","2026.10.26 | 플랫폼 표시값, 계약 가능 여부·승계 조건 미검증")
 lines=[("매매 호가","4.30억",4.30,BLUE),("플랫폼 표시 초기투자금","3.11억",3.11,TEAL)]
 for idx,(label,value,amount,color) in enumerate(lines):
  y=320+idx*175
  d.text((103,y),label,font=font(33,True),fill=NAVY)
  d.rounded_rectangle((510,y,1250,y+57),radius=16,fill=LIGHT)
  d.rounded_rectangle((510,y,510+round(740*amount/5),y+57),radius=16,fill=color)
  d.text((1040,y-7),value,font=font(39,True),fill=NAVY)
 d.rounded_rectangle((95,690,1340,795),radius=24,fill="#f2f6fb")
 d.text((129,716),"호가 − 표시 초투 = 1.19억 (임대차·대출 조건 미확인)",font=font(31,True),fill=NAVY)
 smalltext(d,"출처: 재개발닷컴 공개 매물 / 취득세·금융비용·추가분담금 별도",827)
 im.save(OUT/"sangbong13_03_entry_price.png",optimize=True)
def chart2():
 im,d=canvas("상봉13구역 · 일반분양 계산 기준","공식 2025년 계획과 2026년 조합 현황을 구분해 보자")
 d.text((97,303),"2025 공식 공급계획",font=font(36,True),fill=NAVY)
 dat=[("소유자분양 409",409,BLUE),("일반분양 566",566,TEAL),("보류지 4",4,ORANGE)]
 x=95;yy=367
 for label,num,color in dat:
  width=round(1240*num/979)
  d.rectangle((x,yy,x+width,yy+92),fill=color)
  x+=width
 d.text((102,485),"분양주택 979세대 = 소유자 409 + 일반분양 566 + 보류지 4",font=font(31),fill=NAVY)
 d.line((98,566,1351,566),fill=LIGHT,width=3)
 d.text((97,595),"2026 서울시 정보몽땅",font=font(34,True),fill=NAVY)
 d.text((98,666),"조합원 451명   ·   토지등소유자 457명",font=font(35,True),fill=BLUE)
 d.rounded_rectangle((98,745,1342,807),radius=16,fill="#f2f6fb")
 d.text((121,755),"979 - 451 = 528세대는 단순 잔여 계산 (확정 일반분양 아님)",font=font(26,True),fill=NAVY)
 smalltext(d,"출처: 서울시 고시 제2025-151호·서울시 정비사업 정보몽땅",829)
 im.save(OUT/"sangbong13_04_supply_scenarios.png",optimize=True)
def chart3():
 im,d=canvas("상봉·망우 인근 아파트 실거래","2026년 개별 계약 사례 · 전용면적 및 입지 차이에 주의")
 dat=[("상봉건영캐스빌",8.57),("상봉태영데시앙",9.60),("한일써너스빌",10.27),("프레미어스엠코",11.50),("사가정센트럴아이파크",15.90)]
 for idx,(label,value) in enumerate(dat):
  y=294+idx*103
  d.text((105,y),label,font=font(27,True),fill=NAVY)
  x=510;length=round(value/17*625)
  d.rounded_rectangle((x,y,x+625,y+47),radius=14,fill=LIGHT)
  d.rounded_rectangle((x,y,x+length,y+47),radius=14,fill=TEAL if idx<4 else BLUE)
  d.text((1160,y),f"{value:.2f}억",font=font(32,True),fill=NAVY)
 smalltext(d,"사례: 전용 79.73~84.94㎡ · 최고가 1건은 전체 시세가 아님",827)
 im.save(OUT/"sangbong13_05_nearby_sales.png",optimize=True)
chart1();chart2();chart3()
for f in ["sangbong13_03_entry_price.png","sangbong13_04_supply_scenarios.png","sangbong13_05_nearby_sales.png"]:
 p=OUT/f
 with Image.open(p) as im:
  im.verify()
 print("GENERATED",str(p),p.stat().st_size)
