#!/usr/bin/env python3
"""Produce three original Sangbong13 investor infographics.
Sources and estimates are identified in each image. Generated locally in Actions.
"""
from PIL import Image,ImageDraw,ImageFont
from pathlib import Path
import os

OUT=Path("social-publisher/media")
OUT.mkdir(parents=True,exist_ok=True)
FONT="/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
BOLD="/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"
assert Path(FONT).exists() and Path(BOLD).exists(),"Korean typeface missing"

NAVY="#101D37"; BLUE="#326BE6"; TEAL="#06B6A4"; MUTED="#64748B"; BG="#F4F7FC"; LINE="#DDE5F0"; WHITE="#FFFFFF"; ORANGE="#E69248"
def f(size,bold=False):return ImageFont.truetype(BOLD if bold else FONT,size)
def base(title,subtitle):
 im=Image.new("RGB",(1600,920),BG);d=ImageDraw.Draw(im)
 d.rounded_rectangle((48,40,1552,880),radius=30,fill=WHITE)
 d.rounded_rectangle((48,40,1552,176),radius=30,fill=NAVY)
 d.rectangle((48,124,1552,176),fill=NAVY)
 d.text((100,67),title,font=f(50,True),fill=WHITE)
 d.text((100,196),subtitle,font=f(27),fill=MUTED)
 return im,d
def tag(d,x,y,text,color=NAVY,size=31):d.text((x,y),text,font=f(size,True),fill=color)
def label(d,x,y,text,size=28,color=MUTED):d.text((x,y),text,font=f(size),fill=color)
def foot(d,text):
 d.line((100,803,1500,803),fill=LINE,width=2)
 label(d,100,822,text,20,color=MUTED)
def save(im,name):im.save(OUT/name,format="PNG",optimize=True);print(name, (OUT/name).stat().st_size)

im,d=base("상봉13구역 | 4억대 매물 진입비용","2026.10.26 민간 플랫폼 공개 호가 · 실제 필요 현금은 개별 확인")
d.rounded_rectangle((100,288,760,550),radius=24,fill="#EAF0FF")
d.rounded_rectangle((804,288,1460,550),radius=24,fill="#E6F8F4")
tag(d,139,315,"매매 호가",NAVY,34)
tag(d,847,315,"플랫폼 표시 초기투자금",NAVY,31)
tag(d,139,385,"4.30억 원",BLUE,85)
tag(d,847,385,"3.11억 원",TEAL,85)
d.line((100,620,1460,620),fill=LINE,width=2)
tag(d,109,648,"표시 차액",NAVY,33)
tag(d,403,638,"1억 1,900만 원",ORANGE,48)
tag(d,894,648,"해당 매물 대지지분  7.61평",NAVY,28)
foot(d,"※ 초투는 확정 현금이 아니며 임대차·대출승계, 취득비용 및 추가분담금 별도 확인")
save(im,"sangbong13_03_entry_price.png")

im,d=base("상봉13구역 | 공급 계획과 조합원 비교","공식 2025년 정비계획과 2026년 조합현황은 기준이 다름")
d.rounded_rectangle((100,282,1495,510),radius=18,fill="#EDF3FF")
tag(d,131,300,"2025년 공식 분양주택 979세대 구성",NAVY,31)
start=140; yy=372; total=1320
for count,color,name in [(409,BLUE,"소유자 409"),(566,TEAL,"일반 566"),(4,ORANGE,"보류지 4")]:
 w=max(8,int(total*count/979))
 d.rectangle((start,yy,start+w,yy+70),fill=color)
 start+=w
label(d,144,467,"소유자분양 409세대  ·  일반분양 566세대  ·  보류지 4세대",25,NAVY)
d.rounded_rectangle((100,540,1495,758),radius=20,fill="#E7F8F5")
tag(d,134,560,"2026년 서울시 조합 현황",NAVY,32)
tag(d,140,624,"조합원 451명",TEAL,55)
tag(d,837,631,"토지등소유자 457명",NAVY,40)
foot(d,"※ 단순 잔여세대(979−451=528)는 확정 일반분양이 아님 · 보류지/분양신청 반영 필요")
save(im,"sangbong13_04_supply_scenarios.png")

im,d=base("상봉·망우 생활권 | 아파트 개별 실거래","2026년 7~10월 개별 계약사례 · 단지별 연식/면적/입지 서로 다름")
items=[
 ("상봉건영캐스빌","84.70㎡ · 07.01",8.57),
 ("상봉태영데시앙","84.94㎡ · 08.29",9.60),
 ("한일써너스빌","84.64㎡ · 10.02",10.27),
 ("프레미어스엠코","79.73㎡ · 07.25",11.50),
 ("사가정센트럴아이파크","84.87㎡ · 10.08",15.90)
]
for i,(name,detail,val) in enumerate(items):
 y=293+i*102
 label(d,107,y,name,28,NAVY)
 label(d,107,y+38,detail,20,MUTED)
 w=int((val/17)*820)
 d.rounded_rectangle((550,y+12,550+w,y+60),radius=10,fill=BLUE if i!=4 else TEAL)
 tag(d,590+w,y+13,f"{val:.2f}억",NAVY,31)
foot(d,"※ 서로 다른 개별 거래 비교; 상봉13구역의 미래 신축 시세나 분양가 예측 아님")
save(im,"sangbong13_05_nearby_sales.png")
