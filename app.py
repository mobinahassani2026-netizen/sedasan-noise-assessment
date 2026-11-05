# -*- coding: utf-8 -*-
import gradio as gr
import pandas as pd
import numpy as np
import sqlite3
import math
import tempfile
import os
from datetime import datetime

APP_NAME = "صداسنج | سامانه ارزیابی مواجهه شغلی با صدا"
DB_NAME = "sedasan.db"

# ---------------- DATABASE ----------------

def init_database():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS assessments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            workplace TEXT,
            department TEXT,
            job TEXT,
            lex REAL,
            niosh_dose REAL,
            osha_dose REAL,
            risk TEXT
        )
    """)

    conn.commit()
    conn.close()


# ---------------- VALIDATION ----------------

def validate_data(df):
    if df is None or not isinstance(df, pd.DataFrame):
        raise ValueError("جدول اندازه‌گیری خالی است.")

    required = [
        "فعالیت",
        "تراز صدا dB(A)",
        "مدت مواجهه (ساعت)"
    ]

    if not all(col in df.columns for col in required):
        raise ValueError("ساختار ستون‌های جدول صحیح نیست.")

    data = df[required].copy()

    data["فعالیت"] = data["فعالیت"].fillna("").astype(str)
    data["تراز صدا dB(A)"] = pd.to_numeric(
        data["تراز صدا dB(A)"], errors="coerce"
    )
    data["مدت مواجهه (ساعت)"] = pd.to_numeric(
        data["مدت مواجهه (ساعت)"], errors="coerce"
    )

    if data.empty:
        raise ValueError("حداقل یک فعالیت وارد کنید.")

    if data.isnull().any().any():
        raise ValueError("اطلاعات جدول ناقص یا غیرعددی است.")

    if (data["فعالیت"].str.strip() == "").any():
        raise ValueError("نام فعالیت را وارد کنید.")

    if not data["تراز صدا dB(A)"].between(0, 140).all():
        raise ValueError("تراز صدا باید بین صفر تا 140 باشد.")

    if not (data["مدت مواجهه (ساعت)"] > 0).all():
        raise ValueError("مدت مواجهه باید بیشتر از صفر باشد.")

    if data["مدت مواجهه (ساعت)"].sum() > 24:
        raise ValueError("مجموع مدت مواجهه نباید بیشتر از 24 ساعت باشد.")

    return data


# ---------------- DAILY EXPOSURE ----------------

def calculate_lex(data):
    """
    محاسبه سطح مواجهه روزانه نرمال‌شده به 8 ساعت.
    فرض: زمان باقیمانده در دوره مرجع، مواجهه شغلی صوتی ندارد.
    """

    energy = (
        data["مدت مواجهه (ساعت)"] *
        10 ** (data["تراز صدا dB(A)"] / 10)
    ).sum()

    if energy <= 0:
        raise ValueError("انرژی صوتی محاسبه‌شده معتبر نیست.")

    lex = 10 * math.log10(energy / 8)

    return lex


# ---------------- NIOSH ----------------

def calculate_niosh(data):
    """
    معیار NIOSH:
    85 dB(A)
    نرخ تبادل 3 dB
    مدت معیار 8 ساعت
    """

    levels = data["تراز صدا dB(A)"]
    durations = data["مدت مواجهه (ساعت)"]

    allowed_time = 8 * 2 ** ((85 - levels) / 3)

    dose = (durations / allowed_time).sum() * 100

    return float(dose)


def calculate_niosh_twa(dose):
    if dose <= 0:
        return None

    return 85 + 10 * math.log10(dose / 100)


# ---------------- OSHA ----------------

def calculate_osha(data):
    """
    محاسبه ساده‌شده دوز OSHA:
    90 dB(A)
    نرخ تبادل 5 dB
    مدت معیار 8 ساعت
    """

    levels = data["تراز صدا dB(A)"]
    durations = data["مدت مواجهه (ساعت)"]

    allowed_time = 8 * 2 ** ((90 - levels) / 5)

    dose = (durations / allowed_time).sum() * 100

    return float(dose)


# ---------------- RISK ASSESSMENT ----------------

def assess_eu_risk(lex):

    if lex >= 87:
        return (
            "🔴 بالاتر از حد مواجهه",
            "اقدام فوری برای کاهش مواجهه ضروری است."
        )

    elif lex >= 85:
        return (
            "🟠 بالاتر از حد اقدام بالایی",
            "برنامه کنترل مواجهه و حفاظت شنوایی اجرا شود."
        )

    elif lex >= 80:
        return (
            "🟡 بالاتر از حد اقدام پایینی",
            "آموزش، اطلاع‌رسانی و پایش شنوایی لازم است."
        )

    else:
        return (
            "🟢 پایین‌تر از حد اقدام پایینی",
            "پایش دوره‌ای و اقدامات پیشگیرانه ادامه یابد."
        )


def assess_niosh_risk(dose):

    if dose >= 100:
        return "🔴 ریسک زیاد"

    elif dose >= 50:
        return "🟠 ریسک قابل توجه"

    else:
        return "🟢 پایین‌تر از معیار دوز NIOSH"


# ---------------- ENGINE ----------------

def run_assessment(
    workplace,
    department,
    job,
    measurements
):

    try:

        data = validate_data(measurements)

        lex = calculate_lex(data)
        niosh = calculate_niosh(data)
        osha = calculate_osha(data)
        twa = calculate_niosh_twa(niosh)

        eu_risk, eu_action = assess_eu_risk(lex)
        niosh_risk = assess_niosh_risk(niosh)

        result = f"""
# 🔊 نتیجه ارزیابی مواجهه شغلی با صدا

### مشخصات محیط کار

- کارگاه: {workplace}
- بخش: {department}
- شغل: {job}
- تاریخ: {datetime.now().strftime('%Y-%m-%d %H:%M')}

---

### نتایج محاسبات

| شاخص | نتیجه |
|---|---:|
| مواجهه روزانه LEX,8h | {lex:.2f} dB(A) |
| دوز NIOSH | {niosh:.2f} % |
| TWA برآوردی NIOSH | {twa:.2f} dB(A) |
| دوز OSHA | {osha:.2f} % |

---

### ارزیابی ریسک بر اساس حدود اتحادیه اروپا

**{eu_risk}**

{eu_action}

### ارزیابی بر اساس دوز NIOSH

**{niosh_risk}**

---

### پیشنهاد اقدامات کنترلی

1. بررسی امکان حذف یا جایگزینی منبع پرصدا.
2. استفاده از محفظه آکوستیکی برای ماشین‌آلات.
3. نصب جاذب و عایق صوتی مناسب.
4. افزایش فاصله کارکنان از منابع صدا.
5. کاهش زمان مواجهه و چرخش شغلی در صورت لزوم.
6. انتخاب حفاظت شنوایی متناسب با میزان مواجهه.
7. انجام پایش دوره‌ای و ارزیابی مجدد.

**توجه:** این محاسبات ابزار غربالگری هستند و جایگزین ارزیابی کامل ISO 9612، اندازه‌گیری کالیبره‌شده و مقررات ملی نیستند.
"""

        summary = pd.DataFrame({
            "شاخص": [
                "LEX,8h",
                "دوز NIOSH",
                "TWA NIOSH",
                "دوز OSHA"
            ],
            "مقدار": [
                round(lex, 2),
                round(niosh, 2),
                round(twa, 2),
                round(osha, 2)
            ],
            "واحد": [
                "dB(A)",
                "%",
                "dB(A)",
                "%"
            ]
        })

        return result, summary

    except Exception as error:
        return f"❌ خطا: {str(error)}", pd.DataFrame()


# ---------------- SAVE DATA ----------------

def save_assessment(
    workplace,
    department,
    job,
    measurements
):

    try:

        data = validate_data(measurements)

        lex = calculate_lex(data)
        niosh = calculate_niosh(data)
        osha = calculate_osha(data)
        risk, _ = assess_eu_risk(lex)

        conn = sqlite3.connect(DB_NAME)

        conn.execute("""
            INSERT INTO assessments
            (date, workplace, department, job,
             lex, niosh_dose, osha_dose, risk)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            datetime.now().isoformat(timespec="seconds"),
            workplace,
            department,
            job,
            lex,
            niosh,
            osha,
            risk
        ))

        conn.commit()
        conn.close()

        return "✅ ارزیابی با موفقیت در بانک اطلاعاتی ذخیره شد."

    except Exception as error:
        return f"❌ خطا در ذخیره اطلاعات: {error}"


# ---------------- HISTORY ----------------

def show_history():

    try:

        conn = sqlite3.connect(DB_NAME)

        history = pd.read_sql_query(
            "SELECT * FROM assessments ORDER BY id DESC",
            conn
        )

        conn.close()

        if history.empty:
            return pd.DataFrame(), "هنوز ارزیابی ثبت نشده است."

        return history, "سوابق ارزیابی با موفقیت دریافت شد."

    except Exception as error:
        return pd.DataFrame(), str(error)


# ---------------- EXCEL IMPORT ----------------

def import_excel(file):

    if file is None:
        return pd.DataFrame()

    try:

        data = pd.read_excel(file)

        validate_data(data)

        return data

    except Exception as error:
        raise gr.Error(f"خطا در فایل اکسل: {error}")


# ---------------- EXCEL EXPORT ----------------

def export_excel(measurements):

    try:

        data = validate_data(measurements)

        lex = calculate_lex(data)
        niosh = calculate_niosh(data)
        osha = calculate_osha(data)

        output = tempfile.NamedTemporaryFile(
            suffix=".xlsx",
            delete=False
        )

        output.close()

        with pd.ExcelWriter(
            output.name,
            engine="openpyxl"
        ) as writer:

            data.to_excel(
                writer,
                index=False,
                sheet_name="اندازه گیری"
            )

            pd.DataFrame({
                "شاخص": [
                    "LEX,8h",
                    "NIOSH Dose",
                    "OSHA Dose"
                ],
                "مقدار": [
                    lex,
                    niosh,
                    osha
                ]
            }).to_excel(
                writer,
                index=False,
                sheet_name="نتایج"
            )

        return output.name

    except Exception as error:
        raise gr.Error(f"خطا در ساخت Excel: {error}")


# ---------------- USER INTERFACE ----------------

init_database()

sample_data = pd.DataFrame([
    {
        "فعالیت": "دستگاه برش",
        "تراز صدا dB(A)": 95,
        "مدت مواجهه (ساعت)": 2
    },
    {
        "فعالیت": "دستگاه پرس",
        "تراز صدا dB(A)": 90,
        "مدت مواجهه (ساعت)": 3
    },
    {
        "فعالیت": "مونتاژ",
        "تراز صدا dB(A)": 85,
        "مدت مواجهه (ساعت)": 3
    }
])


with gr.Blocks(
    title=APP_NAME,
    theme=gr.themes.Soft(),
    css="""
    body {
        direction: rtl;
        text-align: right;
    }
    .gradio-container {
        direction: rtl;
    }
    """
) as demo:

    gr.Markdown("""
    # 🔊 صداسنج
    ### سامانه هوشمند ارزیابی مواجهه شغلی با صدا

    ثبت اندازه‌گیری، محاسبه دوز، ارزیابی ریسک و تهیه گزارش.
    """)

    with gr.Tab("ارزیابی جدید"):

        gr.Markdown("## مشخصات محیط کار")

        workplace = gr.Textbox(
            label="نام کارگاه",
            value="کارگاه نمونه"
        )

        department = gr.Textbox(
            label="بخش",
            value="تولید"
        )

        job = gr.Textbox(
            label="عنوان شغلی",
            value="اپراتور دستگاه"
        )

        gr.Markdown("## اطلاعات اندازه‌گیری")

        measurements = gr.Dataframe(
            value=sample_data,
            headers=[
                "فعالیت",
                "تراز صدا dB(A)",
                "مدت مواجهه (ساعت)"
            ],
            datatype=["str", "number", "number"],
            row_count=(3, "dynamic"),
            col_count=(3, "fixed"),
            interactive=True,
            label="جدول اندازه‌گیری صدا"
        )

        excel_input = gr.File(
            label="بارگذاری فایل Excel",
            file_types=[".xlsx"]
        )

        excel_input.change(
            fn=import_excel,
            inputs=excel_input,
            outputs=measurements
        )

        calculate_button = gr.Button(
            "🧮 محاسبه و ارزیابی ریسک",
            variant="primary"
        )

        result = gr.Markdown()

        summary_table = gr.Dataframe(
            label="خلاصه محاسبات",
            interactive=False
        )

        calculate_button.click(
            fn=run_assessment,
            inputs=[
                workplace,
                department,
                job,
                measurements
            ],
            outputs=[
                result,
                summary_table
            ]
        )

        save_button = gr.Button(
            "💾 ذخیره در بانک اطلاعاتی"
        )

        save_message = gr.Markdown()

        save_button.click(
            fn=save_assessment,
            inputs=[
                workplace,
                department,
                job,
                measurements
            ],
            outputs=save_message
        )

        export_button = gr.Button(
            "📥 دریافت گزارش Excel"
        )

        excel_output = gr.File(
            label="فایل گزارش"
        )

        export_button.click(
            fn=export_excel,
            inputs=measurements,
            outputs=excel_output
        )

    with gr.Tab("بانک اطلاعاتی"):

        gr.Markdown("## سوابق ارزیابی‌های ثبت‌شده")

        history_button = gr.Button(
            "نمایش سوابق"
        )

        history_table = gr.Dataframe(
            interactive=False
        )

        history_message = gr.Markdown()

        history_button.click(
            fn=show_history,
            inputs=None,
            outputs=[
                history_table,
                history_message
            ]
        )

    with gr.Tab("استانداردها و راهنما"):

        gr.Markdown("""
        ## استانداردهای مرجع

        ### ISO 9612
        روش تعیین مواجهه شغلی با صدا.

        ### NIOSH REL
        - معیار 85 dB(A)
        - نرخ تبادل 3 dB
        - مدت معیار 8 ساعت

        ### OSHA PEL
        - معیار 90 dB(A)
        - نرخ تبادل 5 dB
        - مدت معیار 8 ساعت

        ### دستورالعمل اتحادیه اروپا 2003/10/EC
        - حد اقدام پایین: 80 dB(A)
        - حد اقدام بالا: 85 dB(A)
        - حد مواجهه: 87 dB(A)

        **نکته:** حدود اتحادیه اروپا با لحاظ شرایط مربوط به حفاظت شنوایی تعریف شده‌اند.
        این نسخه محاسبه کامل ISO 9612 و عدم‌قطعیت اندازه‌گیری را اجرا نمی‌کند.
        """)

    with gr.Tab("درباره برنامه"):

        gr.Markdown("""
        # صداسنج

        نرم‌افزار پشتیبان ارزیابی مواجهه شغلی با صدا.

        امکانات:
        - محاسبه مواجهه روزانه
        - ارزیابی ریسک
        - محاسبه دوز NIOSH و OSHA
        - بانک اطلاعاتی
        - ورود و خروج Excel

        این برنامه خودش صدای محیط را اندازه‌گیری نمی‌کند.
        اطلاعات باید از صداسنج یا دوزیمتر معتبر وارد شوند.
        """)


demo.launch()
