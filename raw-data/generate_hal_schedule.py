"""
generate_hal_schedule.py

สร้างไฟล์ Excel ตารางเรือ (Vessel Schedule) ของสายเรือ HEUNG-A LINE (HAL)
เส้นทาง Bangkok (BKK) และ Laem Chabang (LCH) ไป Ho Chi Minh / Cat Lai (SGN)
ช่วงเดือนกันยายน - ธันวาคม 2026

ข้อมูลดึงมาจากหน้าเว็บ https://ebiz.heungaline.com/Schedule (Outbound / List view)
เมื่อวันที่ 13 กันยายน 2026 — ตารางเรืออาจมีการเปลี่ยนแปลง กรุณายืนยันกับ HAL อีกครั้ง
ก่อนทำการจองจริง

วิธีใช้งาน:
    pip install openpyxl
    python generate_hal_schedule.py

ผลลัพธ์: ไฟล์ HAL_Schedule_Bangkok_LaemChabang_to_HoChiMinh_Sep-Dec2026.xlsx
         (2 ชีท: Bangkok-HoChiMinh และ LaemChabang-HoChiMinh)
"""

import os
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

# Data extracted from https://ebiz.heungaline.com/Schedule (Heung-A Line e-Service)
# Columns: Service, Vessel, Voyage, POL Terminal, POD Terminal, ETD, ETA, Transit, DOCU Closing, CNTR Closing, Booking Status

bangkok_rows = [
["KST","KMTC ULSAN","2614N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-09-02 06:00","2026-09-04 16:00","2 Days 10 Hours","2026-08-28 12:00","2026-08-31 18:00","Closed"],
["BTS","SAWASDEE SPICA","2608N","Bangkok - PAT TERMINAL 1 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-09-06 11:48","2026-09-09 04:18","2 Days 16 Hours","2026-09-03 15:00","2026-09-04 23:59","Closed"],
["KHS1","KMTC BANGKOK","2610N","Bangkok - PAT TERMINAL 2 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-09-11 15:00","2026-09-14 02:00","2 Days 11 Hours","2026-09-04 17:00","2026-09-08 21:00","Closed"],
["KST","SAWASDEE CAPELLA","2609N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-09-11 18:00","2026-09-15 01:00","3 Days 7 Hours","2026-09-09 17:00","2026-09-10 17:00","Closed"],
["NTX","DONGJIN CONFIDENT","0151N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-09-19 07:00","2026-09-22 00:30","2 Days 17 Hours","2026-09-16 17:00","2026-09-17 17:00","Able"],
["KHS1","SAWASDEE INCHEON","2610N","Bangkok - PAT TERMINAL 2 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-09-21 13:00","2026-09-24 00:00","2 Days 11 Hours","2026-09-18 17:00","2026-09-19 12:00","Able"],
["NTX","SAWASDEE BALTIC","2615N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-09-21 17:00","2026-09-24 10:30","2 Days 17 Hours","2026-09-18 17:00","2026-09-18 23:59","Able"],
["NTX","PEGASUS PROTO","2611N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-09-22 10:30","2026-09-25 03:00","2 Days 16 Hours","2026-09-18 17:00","2026-09-19 17:00","Able"],
["KST","KMTC ULSAN","2615N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-09-22 21:00","2026-09-25 08:00","2 Days 11 Hours","2026-09-18 17:00","2026-09-20 12:00","Able"],
["BTS","SAWASDEE MIMOSA","2609N","Bangkok - PAT TERMINAL 1 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-09-23 07:00","2026-09-26 15:00","3 Days 8 Hours","2026-09-18 17:00","2026-09-20 23:59","Able"],
["KST","SAWASDEE ALTAIR","2608N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-09-28 15:00","2026-09-30 23:00","2 Days 8 Hours","2026-09-25 17:00","2026-09-26 23:59","Able"],
["KHS1","KMTC BANGKOK","2611N","Bangkok - PAT TERMINAL 2 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-10-02 08:00","2026-10-04 18:00","2 Days 10 Hours","2026-09-28 17:00","2026-09-29 19:00","Able"],
["BTS","SAWASDEE SPICA","2609N","Bangkok - PAT TERMINAL 1 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-10-01 20:30","2026-10-05 04:30","3 Days 8 Hours","2026-09-28 12:00","2026-09-29 18:00","Able"],
["NTX","DONGJIN CONFIDENT","0152N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-10-10 07:00","2026-10-13 00:30","2 Days 17 Hours","2026-10-07 17:00","2026-10-08 17:00","Able"],
["KST","KMTC ULSAN","2616N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-10-12 15:00","2026-10-14 23:00","2 Days 8 Hours","2026-10-09 17:00","2026-10-10 18:00","Able"],
["NTX","SAWASDEE BALTIC","2616N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-10-12 07:30","2026-10-15 01:00","2 Days 17 Hours","2026-10-08 17:00","2026-10-09 23:59","Able"],
["KHS1","SAWASDEE INCHEON","2611N","Bangkok - PAT TERMINAL 2 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-10-13 02:00","2026-10-15 15:00","2 Days 13 Hours","2026-10-09 17:00","2026-10-10 12:00","Able"],
["NTX","PEGASUS PROTO","2612N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-10-13 01:30","2026-10-15 19:00","2 Days 17 Hours","2026-10-09 17:00","2026-10-10 17:00","Able"],
["KHS1","HEUNG-A HOCHIMINH","2612N","Bangkok - PAT TERMINAL 2 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-10-15 00:00","2026-10-17 10:00","2 Days 10 Hours","2026-10-09 17:00","2026-10-12 12:00","Able"],
["BTS","SAWASDEE MIMOSA","2610N","Bangkok - PAT TERMINAL 1 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-10-18 07:00","2026-10-21 15:00","3 Days 8 Hours","2026-10-14 17:00","2026-10-15 23:59","Able"],
["KST","SAWASDEE ALTAIR","2609N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-10-19 15:00","2026-10-21 23:00","2 Days 8 Hours","2026-10-16 17:00","2026-10-17 18:00","Able"],
["KHS1","KMTC BANGKOK","2612N","Bangkok - PAT TERMINAL 2 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-10-22 18:00","2026-10-25 04:00","2 Days 10 Hours","2026-10-19 12:00","2026-10-20 12:00","Able"],
["BTS","SAWASDEE SPICA","2610N","Bangkok - PAT TERMINAL 1 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-10-23 20:30","2026-10-26 04:30","2 Days 8 Hours","2026-10-19 17:00","2026-10-20 23:59","Able"],
["KST","PANCON CHAMPION","2611N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-10-28 10:00","2026-10-30 18:00","2 Days 8 Hours","2026-10-27 17:00","2026-10-28 12:00","Able"],
["NTX","DONGJIN CONFIDENT","0153N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-10-31 07:00","2026-11-03 00:30","2 Days 17 Hours","2026-10-28 12:00","2026-10-29 17:00","Able"],
["KST","KMTC ULSAN","2617N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-11-02 16:00","2026-11-05 00:00","2 Days 8 Hours","-","-","Able"],
["NTX","SAWASDEE BALTIC","2617N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-11-02 07:30","2026-11-05 01:00","2 Days 17 Hours","2026-10-29 17:00","2026-10-30 23:59","Able"],
["NTX","PEGASUS PROTO","2613N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-11-03 01:30","2026-11-05 19:00","2 Days 17 Hours","-","-","Able"],
["KHS1","SAWASDEE INCHEON","2612N","Bangkok - PAT TERMINAL 2 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-11-04 06:00","2026-11-06 18:00","2 Days 12 Hours","2026-10-27 17:00","2026-10-28 23:59","Able"],
["KHS1","HEUNG-A HOCHIMINH","2613N","Bangkok - PAT TERMINAL 2 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-11-06 13:00","2026-11-08 23:00","2 Days 10 Hours","-","-","Able"],
["BTS","SAWASDEE MIMOSA","2611N","Bangkok - PAT TERMINAL 1 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-11-09 07:00","2026-11-11 15:00","2 Days 8 Hours","-","-","Able"],
["KST","SAWASDEE ALTAIR","2610N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-11-09 15:00","2026-11-11 23:00","2 Days 8 Hours","-","-","Able"],
["KHS1","KMTC BANGKOK","2613N","Bangkok - PAT TERMINAL 2 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-11-12 01:00","2026-11-14 11:00","2 Days 10 Hours","-","-","Able"],
["BTS","SAWASDEE SPICA","2611N","Bangkok - PAT TERMINAL 1 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-11-14 10:26","2026-11-16 18:26","2 Days 8 Hours","-","-","Able"],
["KST","PANCON CHAMPION","2612N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-11-20 05:00","2026-11-22 13:00","2 Days 8 Hours","-","-","Able"],
["NTX","DONGJIN CONFIDENT","0154N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-11-21 07:00","2026-11-24 00:30","2 Days 17 Hours","-","-","Able"],
["KST","KMTC ULSAN","2618N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-11-23 16:00","2026-11-26 00:00","2 Days 8 Hours","-","-","Able"],
["NTX","SAWASDEE BALTIC","2618N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-11-23 07:30","2026-11-26 01:00","2 Days 17 Hours","-","-","Able"],
["NTX","PEGASUS PROTO","2614N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-11-24 01:30","2026-11-26 19:00","2 Days 17 Hours","-","-","Able"],
["KHS1","SAWASDEE INCHEON","2613N","Bangkok - PAT TERMINAL 2 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-11-24 22:00","2026-11-27 08:00","2 Days 10 Hours","-","-","Able"],
["KHS1","HEUNG-A HOCHIMINH","2614N","Bangkok - PAT TERMINAL 2 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-11-27 11:00","2026-11-29 21:00","2 Days 10 Hours","-","-","Able"],
["BTS","SAWASDEE MIMOSA","2612N","Bangkok - PAT TERMINAL 1 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-11-30 07:00","2026-12-02 15:00","2 Days 8 Hours","-","-","Able"],
["KHS1","KMTC BANGKOK","2614N","Bangkok - PAT TERMINAL 2 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-11-30 11:00","2026-12-02 21:00","2 Days 10 Hours","-","-","Able"],
["KST","SAWASDEE ALTAIR","2611N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-11-30 15:00","2026-12-02 23:00","2 Days 8 Hours","2026-10-16 17:00","2026-10-17 18:00","Able"],
["BTS","SAWASDEE SPICA","2612N","Bangkok - PAT TERMINAL 1 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-12-05 10:22","2026-12-07 18:22","2 Days 8 Hours","-","-","Able"],
["KST","PANCON CHAMPION","2613N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-12-11 05:00","2026-12-13 13:00","2 Days 8 Hours","-","-","Able"],
["NTX","DONGJIN CONFIDENT","0155N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-12-12 07:00","2026-12-15 00:30","2 Days 17 Hours","-","-","Able"],
["KST","KMTC ULSAN","2619N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-12-14 16:00","2026-12-17 00:00","2 Days 8 Hours","-","-","Able"],
["NTX","SAWASDEE BALTIC","2619N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-12-14 07:30","2026-12-17 01:00","2 Days 17 Hours","-","-","Able"],
["NTX","PEGASUS PROTO","2615N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-12-15 01:30","2026-12-17 19:00","2 Days 17 Hours","-","-","Able"],
["KHS1","SAWASDEE INCHEON","2614N","Bangkok - PAT TERMINAL 2 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-12-15 19:00","2026-12-18 04:00","2 Days 9 Hours","-","-","Able"],
["KHS1","HEUNG-A HOCHIMINH","2615N","Bangkok - PAT TERMINAL 2 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-12-18 13:00","2026-12-20 23:00","2 Days 10 Hours","-","-","Able"],
["KHS1","KMTC BANGKOK","2615N","Bangkok - PAT TERMINAL 2 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-12-21 04:00","2026-12-23 14:00","2 Days 10 Hours","-","-","Able"],
["BTS","SAWASDEE MIMOSA","2613N","Bangkok - PAT TERMINAL 1 (PORT AUTHORITY OF THAILAND)","Hochiminh - CAT LAI","2026-12-21 07:00","2026-12-23 15:00","2 Days 8 Hours","-","-","Able"],
["KST","SAWASDEE ALTAIR","2612N","Bangkok - UNITHAI CONTAINER TERMINAL","Hochiminh - CAT LAI","2026-12-21 15:00","2026-12-23 23:00","2 Days 8 Hours","-","-","Able"],
]

laem_rows = [
["KST","KMTC ULSAN","2614N","Laem Chabang - ESCO (EASTERN SEA LCH CNTR TML)","Hochiminh - CAT LAI","2026-09-02 22:00","2026-09-04 16:00","1 Days 18 Hours","2026-08-31 17:00","2026-09-01 11:00","Closed"],
["KST","PANCON CHAMPION","2608N","Laem Chabang - LCIT(LAEM CHABANG INTERNATIONAL TERMINAL CO., LTD)","Hochiminh - CAT LAI","2026-09-06 07:10","2026-09-08 08:00","2 Days 0 Hours","2026-09-03 12:00","2026-09-04 07:00","Closed"],
["BTS","SAWASDEE SPICA","2608N","Laem Chabang - ESCO (EASTERN SEA LCH CNTR TML)","Hochiminh - CAT LAI","2026-09-07 05:00","2026-09-09 04:18","1 Days 23 Hours","2026-09-04 12:00","2026-09-05 18:00","Closed"],
["KHS1","KMTC BANGKOK","2610N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-09-12 07:00","2026-09-14 02:00","1 Days 19 Hours","2026-09-08 17:00","2026-09-10 20:00","Closed"],
["KST","SAWASDEE CAPELLA","2609N","Laem Chabang - ESCO (EASTERN SEA LCH CNTR TML)","Hochiminh - CAT LAI","2026-09-12 11:00","2026-09-15 01:00","2 Days 14 Hours","2026-09-10 17:00","2026-09-11 05:00","Closed"],
["NTX","DONGJIN CONFIDENT","0151N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-09-20 01:00","2026-09-22 00:30","1 Days 23 Hours","2026-09-17 17:00","2026-09-18 14:00","Able"],
["KHS1","SAWASDEE INCHEON","2610N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-09-22 05:00","2026-09-24 00:00","1 Days 19 Hours","2026-09-18 17:00","2026-09-20 19:00","Able"],
["NTX","SAWASDEE BALTIC","2615N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-09-22 11:00","2026-09-24 10:30","1 Days 23 Hours","2026-09-18 17:00","2026-09-19 18:00","Able"],
["NTX","PEGASUS PROTO","2611N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-09-23 03:30","2026-09-25 03:00","1 Days 23 Hours","2026-09-18 17:00","2026-09-20 12:00","Able"],
["KST","KMTC ULSAN","2615N","Laem Chabang - LCIT(LAEM CHABANG INTERNATIONAL TERMINAL CO., LTD)","Hochiminh - CAT LAI","2026-09-23 15:00","2026-09-25 08:00","1 Days 17 Hours","2026-09-18 17:00","2026-09-21 09:00","Able"],
["BTS","SAWASDEE MIMOSA","2609N","Laem Chabang - ESCO (EASTERN SEA LCH CNTR TML)","Hochiminh - CAT LAI","2026-09-24 00:00","2026-09-26 15:00","2 Days 15 Hours","2026-09-21 12:00","2026-09-22 12:00","Able"],
["KST","SAWASDEE ALTAIR","2608N","Laem Chabang - LCIT(LAEM CHABANG INTERNATIONAL TERMINAL CO., LTD)","Hochiminh - CAT LAI","2026-09-29 08:00","2026-09-30 23:00","1 Days 15 Hours","2026-09-25 17:00","2026-09-27 20:00","Able"],
["KHS1","KMTC BANGKOK","2611N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-10-03 00:00","2026-10-04 18:00","1 Days 18 Hours","2026-09-30 12:00","2026-10-01 14:00","Able"],
["BTS","SAWASDEE SPICA","2609N","Laem Chabang - ESCO (EASTERN SEA LCH CNTR TML)","Hochiminh - CAT LAI","2026-10-02 13:30","2026-10-05 04:30","2 Days 15 Hours","2026-09-29 12:00","2026-09-30 17:00","Able"],
["KST","PANCON CHAMPION","2610N","Laem Chabang - LCIT(LAEM CHABANG INTERNATIONAL TERMINAL CO., LTD)","Hochiminh - CAT LAI","2026-10-09 02:00","2026-10-10 20:00","1 Days 18 Hours","2026-10-07 17:00","2026-10-08 10:00","Able"],
["NTX","DONGJIN CONFIDENT","0152N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-10-11 01:00","2026-10-13 00:30","1 Days 23 Hours","2026-10-08 17:00","2026-10-09 10:00","Able"],
["KST","KMTC ULSAN","2616N","Laem Chabang - LCIT(LAEM CHABANG INTERNATIONAL TERMINAL CO., LTD)","Hochiminh - CAT LAI","2026-10-13 08:00","2026-10-14 23:00","1 Days 15 Hours","2026-10-09 17:00","2026-10-11 19:00","Able"],
["NTX","SAWASDEE BALTIC","2616N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-10-13 01:30","2026-10-15 01:00","1 Days 23 Hours","2026-10-09 17:00","2026-10-10 18:00","Able"],
["KHS1","SAWASDEE INCHEON","2611N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-10-13 21:00","2026-10-15 15:00","1 Days 18 Hours","2026-10-09 17:00","2026-10-12 12:00","Able"],
["NTX","PEGASUS PROTO","2612N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-10-13 19:30","2026-10-15 19:00","1 Days 23 Hours","2026-10-10 17:00","2026-10-11 11:00","Able"],
["KHS1","HEUNG-A HOCHIMINH","2612N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-10-15 16:00","2026-10-17 10:00","1 Days 18 Hours","2026-10-13 12:00","2026-10-14 12:00","Able"],
["BTS","SAWASDEE MIMOSA","2610N","Laem Chabang - ESCO (EASTERN SEA LCH CNTR TML)","Hochiminh - CAT LAI","2026-10-19 00:00","2026-10-21 15:00","2 Days 15 Hours","2026-10-16 17:00","2026-10-17 12:00","Able"],
["KST","SAWASDEE ALTAIR","2609N","Laem Chabang - LCIT(LAEM CHABANG INTERNATIONAL TERMINAL CO., LTD)","Hochiminh - CAT LAI","2026-10-20 08:00","2026-10-21 23:00","1 Days 15 Hours","2026-10-16 17:00","2026-10-18 20:00","Able"],
["KHS1","KMTC BANGKOK","2612N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-10-23 10:00","2026-10-25 04:00","1 Days 18 Hours","2026-10-20 17:00","2026-10-21 23:59","Able"],
["BTS","SAWASDEE SPICA","2610N","Laem Chabang - ESCO (EASTERN SEA LCH CNTR TML)","Hochiminh - CAT LAI","2026-10-24 13:30","2026-10-26 04:30","1 Days 15 Hours","2026-10-21 12:00","2026-10-22 17:00","Able"],
["KST","PANCON CHAMPION","2611N","Laem Chabang - LCIT(LAEM CHABANG INTERNATIONAL TERMINAL CO., LTD)","Hochiminh - CAT LAI","2026-10-29 03:00","2026-10-30 18:00","1 Days 15 Hours","2026-10-28 17:00","2026-10-29 10:00","Able"],
["NTX","DONGJIN CONFIDENT","0153N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-11-01 01:00","2026-11-03 00:30","1 Days 23 Hours","2026-10-29 17:00","2026-10-30 10:00","Able"],
["KST","KMTC ULSAN","2617N","Laem Chabang - LCIT(LAEM CHABANG INTERNATIONAL TERMINAL CO., LTD)","Hochiminh - CAT LAI","2026-11-03 09:00","2026-11-05 00:00","1 Days 15 Hours","-","-","Able"],
["NTX","SAWASDEE BALTIC","2617N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-11-03 01:30","2026-11-05 01:00","1 Days 23 Hours","2026-10-30 17:00","2026-10-31 18:00","Able"],
["NTX","PEGASUS PROTO","2613N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-11-03 19:30","2026-11-05 19:00","1 Days 23 Hours","-","-","Able"],
["KHS1","SAWASDEE INCHEON","2612N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-11-05 01:00","2026-11-06 18:00","1 Days 17 Hours","2026-10-29 17:00","2026-10-30 20:00","Able"],
["KHS1","HEUNG-A HOCHIMINH","2613N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-11-07 05:00","2026-11-08 23:00","1 Days 18 Hours","-","-","Able"],
["BTS","SAWASDEE MIMOSA","2611N","Laem Chabang - ESCO (EASTERN SEA LCH CNTR TML)","Hochiminh - CAT LAI","2026-11-10 00:00","2026-11-11 15:00","1 Days 15 Hours","-","-","Able"],
["KST","SAWASDEE ALTAIR","2610N","Laem Chabang - LCIT(LAEM CHABANG INTERNATIONAL TERMINAL CO., LTD)","Hochiminh - CAT LAI","2026-11-10 08:00","2026-11-11 23:00","1 Days 15 Hours","-","-","Able"],
["KHS1","KMTC BANGKOK","2613N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-11-12 17:00","2026-11-14 11:00","1 Days 18 Hours","-","-","Able"],
["BTS","SAWASDEE SPICA","2611N","Laem Chabang - ESCO (EASTERN SEA LCH CNTR TML)","Hochiminh - CAT LAI","2026-11-15 03:26","2026-11-16 18:26","1 Days 15 Hours","-","-","Able"],
["KST","PANCON CHAMPION","2612N","Laem Chabang - LCIT(LAEM CHABANG INTERNATIONAL TERMINAL CO., LTD)","Hochiminh - CAT LAI","2026-11-20 22:00","2026-11-22 13:00","1 Days 15 Hours","-","-","Able"],
["NTX","DONGJIN CONFIDENT","0154N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-11-22 01:00","2026-11-24 00:30","1 Days 23 Hours","-","-","Able"],
["KST","KMTC ULSAN","2618N","Laem Chabang - LCIT(LAEM CHABANG INTERNATIONAL TERMINAL CO., LTD)","Hochiminh - CAT LAI","2026-11-24 09:00","2026-11-26 00:00","1 Days 15 Hours","-","-","Able"],
["NTX","SAWASDEE BALTIC","2618N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-11-24 01:30","2026-11-26 01:00","1 Days 23 Hours","-","-","Able"],
["NTX","PEGASUS PROTO","2614N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-11-24 19:30","2026-11-26 19:00","1 Days 23 Hours","-","-","Able"],
["KHS1","SAWASDEE INCHEON","2613N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-11-25 14:00","2026-11-27 08:00","1 Days 18 Hours","-","-","Able"],
["KHS1","HEUNG-A HOCHIMINH","2614N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-11-28 03:00","2026-11-29 21:00","1 Days 18 Hours","-","-","Able"],
["BTS","SAWASDEE MIMOSA","2612N","Laem Chabang - ESCO (EASTERN SEA LCH CNTR TML)","Hochiminh - CAT LAI","2026-12-01 00:00","2026-12-02 15:00","1 Days 15 Hours","-","-","Able"],
["KHS1","KMTC BANGKOK","2614N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-12-01 03:00","2026-12-02 21:00","1 Days 18 Hours","-","-","Able"],
["KST","SAWASDEE ALTAIR","2611N","Laem Chabang - LCIT(LAEM CHABANG INTERNATIONAL TERMINAL CO., LTD)","Hochiminh - CAT LAI","2026-12-01 08:00","2026-12-02 23:00","1 Days 15 Hours","-","-","Able"],
["BTS","SAWASDEE SPICA","2612N","Laem Chabang - ESCO (EASTERN SEA LCH CNTR TML)","Hochiminh - CAT LAI","2026-12-06 03:22","2026-12-07 18:22","1 Days 15 Hours","-","-","Able"],
["KST","PANCON CHAMPION","2613N","Laem Chabang - LCIT(LAEM CHABANG INTERNATIONAL TERMINAL CO., LTD)","Hochiminh - CAT LAI","2026-12-11 22:00","2026-12-13 13:00","1 Days 15 Hours","-","-","Able"],
["NTX","DONGJIN CONFIDENT","0155N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-12-13 01:00","2026-12-15 00:30","1 Days 23 Hours","-","-","Able"],
["KST","KMTC ULSAN","2619N","Laem Chabang - LCIT(LAEM CHABANG INTERNATIONAL TERMINAL CO., LTD)","Hochiminh - CAT LAI","2026-12-15 09:00","2026-12-17 00:00","1 Days 15 Hours","-","-","Able"],
["NTX","SAWASDEE BALTIC","2619N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-12-15 01:30","2026-12-17 01:00","1 Days 23 Hours","-","-","Able"],
["NTX","PEGASUS PROTO","2615N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-12-15 19:30","2026-12-17 19:00","1 Days 23 Hours","-","-","Able"],
["KHS1","SAWASDEE INCHEON","2614N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-12-16 11:00","2026-12-18 04:00","1 Days 17 Hours","-","-","Able"],
["KHS1","HEUNG-A HOCHIMINH","2615N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-12-19 05:00","2026-12-20 23:00","1 Days 18 Hours","-","-","Able"],
["KHS1","KMTC BANGKOK","2615N","Laem Chabang - LCMT Company LTD, (under LCB1 Group) A0","Hochiminh - CAT LAI","2026-12-21 20:00","2026-12-23 14:00","1 Days 18 Hours","-","-","Able"],
["BTS","SAWASDEE MIMOSA","2613N","Laem Chabang - ESCO (EASTERN SEA LCH CNTR TML)","Hochiminh - CAT LAI","2026-12-22 00:00","2026-12-23 15:00","1 Days 15 Hours","-","-","Able"],
["KST","SAWASDEE ALTAIR","2612N","Laem Chabang - LCIT(LAEM CHABANG INTERNATIONAL TERMINAL CO., LTD)","Hochiminh - CAT LAI","2026-12-22 08:00","2026-12-23 23:00","1 Days 15 Hours","-","-","Able"],
]

print("Bangkok rows:", len(bangkok_rows))
print("Laem Chabang rows:", len(laem_rows))

HEADERS = ["Service","Vessel","Voyage","POL / Terminal","POD / Terminal","ETD","ETA","Transit Time","DOCU Closing","CNTR Closing","Booking Status"]

FONT_NAME = "Arial"
header_font = Font(name=FONT_NAME, size=11, bold=True, color="FFFFFF")
header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
title_font = Font(name=FONT_NAME, size=14, bold=True, color="1F4E79")
sub_font = Font(name=FONT_NAME, size=10, italic=True, color="595959")
body_font = Font(name=FONT_NAME, size=10)
closed_font = Font(name=FONT_NAME, size=10, color="C00000")
thin = Side(style="thin", color="D9D9D9")
border = Border(left=thin, right=thin, top=thin, bottom=thin)
center = Alignment(horizontal="center", vertical="center", wrap_text=True)
left = Alignment(horizontal="left", vertical="center", wrap_text=True)

def write_sheet(ws, title, pol_name, rows):
    ws.sheet_view.showGridLines = False
    ws["B2"] = f"HEUNG-A LINE (HAL) — Vessel Schedule: {pol_name} to Ho Chi Minh (CAT LAI)"
    ws["B2"].font = title_font
    ws["B3"] = "Period: September 2026 – December 2026  |  Source: ebiz.heungaline.com/Schedule  |  Schedule is for reference only, please reconfirm with HAL local office before booking."
    ws["B3"].font = sub_font

    start_row = 5
    for j, h in enumerate(HEADERS, start=2):
        c = ws.cell(row=start_row, column=j, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = center
        c.border = border

    r = start_row + 1
    for row in rows:
        for j, val in enumerate(row, start=2):
            c = ws.cell(row=r, column=j, value=val)
            c.border = border
            c.font = closed_font if row[-1] == "Closed" else body_font
            c.alignment = center if j in (2,3,6,7,8,9,10,11) else left
        r += 1

    widths = {2:9, 3:20, 4:9, 5:40, 6:22, 7:17, 8:17, 9:16, 10:17, 11:17, 12:15}
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w

    ws.freeze_panes = f"B{start_row+1}"
    ws.row_dimensions[start_row].height = 30

wb = openpyxl.Workbook()
ws1 = wb.active
ws1.title = "Bangkok-HoChiMinh"
write_sheet(ws1, "Bangkok-HoChiMinh", "Bangkok (BKK)", bangkok_rows)

ws2 = wb.create_sheet("LaemChabang-HoChiMinh")
write_sheet(ws2, "LaemChabang-HoChiMinh", "Laem Chabang (LCH)", laem_rows)

out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "HAL_Schedule_Bangkok_LaemChabang_to_HoChiMinh_Sep-Dec2026.xlsx")
wb.save(out_path)
print("Saved:", out_path)
