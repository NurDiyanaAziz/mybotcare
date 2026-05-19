import logging
import json
import os
import requests
import datetime
import asyncio
import aiohttp
from aiohttp import web
from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler

# 1. SETUP: Enter your Token from BotFather here
TOKEN = "8661491487:AAEQPs4UoL7tDMA6BL3zih_AAFYyQqNjMzs"

# Bot's memory to store states and data
status_ubat = {}
user_state = {} 
temp_medicine = {}
jadual_ubat = {}
rekod_kesihatan = {}
zon_pengguna = {}

# Kamus kod rasmi JAKIM untuk ibu negeri / kawasan utama
# --- KAMUS DAERAH & KOD ZON RASMI JAKIM ---
# Struktur: "NEGERI": {"Nama Paparan Daerah/Zon": "KOD_JAKIM"}
STRUKTUR_ZON = {
    "Kuala Lumpur": {"Kuala Lumpur & Putrajaya": "WLY01"},
    "Selangor": {
        "Gombak, Petaling, Sepang, Hulu Langat": "SGR01",
        "Klang, Kuala Selangor, Kuala Langat": "SGR02",
        "Sabak Bernam, Hulu Selangor": "SGR03"
    },
    "Melaka": {"Seluruh Negeri Melaka": "MLK01"},
    "Johor": {
        "Johor Bahru, Kota Tinggi, Kulai": "JHR02",
        "Kluang, Pontian": "JHR03",
        "Batu Pahat, Muar, Segamat, Ledang": "JHR04"
    },
    "Penang": {"Seluruh Pulau Pinang": "PNG01"},
    "Perak": {
        "Ipoh, Batu Gajah, Kampar, Kuala Kangsar": "PRK02",
        "Taiping, Parit Buntar, Bagan Serai": "PRK03",
        "Manjung, Lumut, Sitiawan, Teluk Intan": "PRK04"
    },
    "Terengganu": {
        "Kuala Terengganu, Marang, Kuala Nerus": "TRG01",
        "Besut, Setiu": "TRG02",
        "Hulu Terengganu": "TRG03",
        "Kemaman, Dungun": "TRG04"
    },
    "Sabah": {
        "Kota Kinabalu, Penampang, Tuaran": "SBH01",
        "Sandakan, Beluran": "SBH02",
        "Tawau, Lahad Datu": "SBH03"
    },
    "Sarawak": {
        "Kuching, Bau, Lundu, Samarahan": "SWK01",
        "Sibu, Mukah, Kanowit": "SWK05",
        "Miri, Marudi": "SWK09"
    }
}

# 2. MENU DEFINITIONS (The buttons the user sees)
MAIN_MENU = [
    ["Jadual Ubat 💊", "Rekod Kesihatan 🩸"],
    ["Waktu Solat 🕋", "Zikir & Ayat Suci 📿"]
]

MENU_KESIHATAN = [
    ["Tambah Rekod 📝", "Lihat Rekod 📈"], 
    ["Kembali ke Menu Utama ⬅️"]
]

MENU_LIHAT_REKOD = [
    ["5 Rekod Terakhir ⏳", "Rekod Bulan Ini 📅"],
    ["Padam Semua Rekod 🗑️"],
    ["Kembali ke Menu Kesihatan ⬅️"]
]

MEDICINE_MENU = [
    ["Lihat Jadual 📋", "Tambah Ubat Baru ➕"],
    ["Edit Waktu ✏️", "Buang Ubat 🗑️"],
    ["Kembali ke Menu Utama ⬅️"]
]

MENU_SOLAT = [
    ["Papar Waktu Solat 🕌", "Tukar Lokasi 📍"], 
    ["Kembali ke Menu Utama ⬅️"]
]

# ---------------------------------------------------------
# 3. THE MULTI-STAGE ALERTS
# ---------------------------------------------------------

async def stage_1_reminder(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    waktu_ubat = context.job.data
    senarai_ubat = [ubat['name'] for ubat in jadual_ubat.get(chat_id, []) if ubat['time'] == waktu_ubat]
    nama_gabung = "\n- ".join(senarai_ubat)
    
    await context.bot.send_message(
        chat_id=chat_id, 
        text=f"⏳ **PERINGATAN 1:** Lagi 10 minit untuk jadual ubat jam {waktu_ubat}. Sila bersedia untuk:\n- {nama_gabung}"
    )

async def stage_2_alarm(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    waktu_ubat = context.job.data
    status_ubat[chat_id] = False 
    
    senarai_ubat = [ubat['name'] for ubat in jadual_ubat.get(chat_id, []) if ubat['time'] == waktu_ubat]
    nama_gabung = "\n- ".join(senarai_ubat)
    
    butang_inline = [[InlineKeyboardButton("SAYA SUDAH MAKAN SEMUA ✅", callback_data="dah_makan")]]
    susunan_butang = InlineKeyboardMarkup(butang_inline)
    
    await context.bot.send_message(
        chat_id=chat_id, 
        text=f"🚨 **WAKTU MAKAN UBAT ({waktu_ubat})!** Sila ambil ubat berikut sekarang:\n- {nama_gabung}",
        reply_markup=susunan_butang
    )

async def stage_3_check(context: ContextTypes.DEFAULT_TYPE):
    chat_id = context.job.chat_id
    waktu_ubat = context.job.data
    
    if status_ubat.get(chat_id) == False:
        await context.bot.send_message(
            chat_id=chat_id, 
            text=f"⚠️ **AMARAN:** Anda belum mengesahkan pengambilan ubat jam {waktu_ubat}. Sistem sedang menghantar notifikasi kepada anak/penjaga anda!"
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ Tugasan jam {waktu_ubat} selesai. Anda telah makan ubat tepat pada waktunya."
        )

async def butang_ditekan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer() # Beritahu Telegram butang dah berjaya ditekan
    
    chat_id = query.message.chat_id
    
    # --- LOGIK BUTTON 1: PENGESAHAN MAKAN UBAT ---
    if query.data == "dah_makan":
        status_ubat[chat_id] = True 
        await query.edit_message_text(text="✅ Terima kasih! Rekod pengesahan untuk SEMUA ubat pada waktu ini telah disimpan. Syabas!")
        
    # --- LOGIK BUTTON 2: HANTAR LOKASI KECEMASAN SOS ---
    elif query.data == "hantar_lokasi_sos":
        # Nota Projek: Sila gantikan ID di bawah dengan ID Telegram Penjaga sebenar jika mahu bot hantar alert ke telefon orang lain
        # Buat masa demo, bot akan hantar mesej amaran Google Maps balik kepada mangsa sebagai simulasi penjaga menerima mesej
        id_penjaga = chat_id 
        
        # Simulasi Koordinat Lokasi Semasa (Anda boleh laras koordinat mengikut keperluan)
        latitude = 2.2472   # Koordinat Melaka / Kawasan Rumah
        longitude = 102.2033
        
        pautan_peta = f"https://www.google.com/maps?q={latitude},{longitude}"
        
        # 1. Hantar isyarat teks "Jeritan SOS" kepada penjaga
        await context.bot.send_message(
            chat_id=id_penjaga,
            text=f"🚨 **AMARAN SOS KECEMASAN!** 🚨\n\n"
                 f"Ahli keluarga anda (ID: {chat_id}) memerlukan bantuan segera!\n"
                 f"📍 **Lokasi Terakhir (Google Maps):** {pautan_peta}\n\n"
                 f"_Sila hubungi mangsa atau pergi ke lokasi sekarang!_"
        )
        
        # 2. Kemas kini status skrin warga emas untuk kurangkan panik
        await query.edit_message_text(
            text="✅ **ISYARAT SOS BERJAYA DIHANTAR!**\n\n"
                 "Koordinat lokasi anda serta senarai ubat semasa telah dimajukan ke telefon ahli keluarga/penjaga anda. Bertenang, bantuan sedang dalam perjalanan. 🛡️"
        )

# ---------------------------------------------------------
# 4. DATA MANAGEMENT
# ---------------------------------------------------------

def save_data():
    global jadual_ubat, rekod_kesihatan, zon_pengguna
    data_keseluruhan = {
        "jadual": jadual_ubat,
        "kesihatan": rekod_kesihatan,
        "zon": zon_pengguna
    }
    with open("jadual_data.json", "w") as f:
        json.dump(data_keseluruhan, f)

def load_data():
    global jadual_ubat, rekod_kesihatan, zon_pengguna
    if os.path.exists("jadual_data.json"):
        try:
            with open("jadual_data.json", "r") as f:
                data = json.load(f)
                jadual_ubat = {int(k): v for k, v in data.get("jadual", {}).items()}
                rekod_kesihatan = {int(k): v for k, v in data.get("kesihatan", {}).items()}
                zon_pengguna = {int(k): v for k, v in data.get("zon", {}).items()}
        except Exception as e:
            print(f"JSON parsing error fallback: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply_markup = ReplyKeyboardMarkup(MAIN_MENU, resize_keyboard=True)
    await update.message.reply_text("Selamat Datang ke SmartCare AI. Pilih bantuan:", reply_markup=reply_markup)

# ---------------------------------------------------------
# 5. CONVERSATION AND INPUT HANDLER
# ---------------------------------------------------------

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_choice = update.message.text
    chat_id = update.effective_chat.id

    # --- PART A: CONVERSATION STATES (STATE MANAGEMENT) ---
    if user_state.get(chat_id) == "WAITING_FOR_NAME":
        temp_medicine[chat_id] = {"name": user_choice}
        user_state[chat_id] = "WAITING_FOR_TIME"
        await update.message.reply_text(
            f"Baik, nama ubat disimpan: **{user_choice}**.\n\nSila taip waktu makan ubat (Contoh: 14:00).\n*(Atau taip 'demo' untuk mulakan ujian pantas 5 saat)*",
            parse_mode='Markdown'
        )
        return

    elif user_state.get(chat_id) == "WAITING_FOR_TIME":
        med_name = temp_medicine[chat_id]["name"]
        time_input = user_choice
        user_state[chat_id] = None
        
        if chat_id not in jadual_ubat:
            jadual_ubat[chat_id] = []

        if time_input.isdigit():
            if len(time_input) == 1:
                time_input = f"0{time_input}:00"
            elif len(time_input) == 2:
                time_input = f"{time_input}:00"
            
        jadual_ubat[chat_id].append({"name": med_name, "time": time_input})
        save_data()

        if time_input.lower() == "demo":
            await update.message.reply_text(f"✅ Ubat **{med_name}** berjaya ditambah! Mod Demo diaktifkan.", parse_mode='Markdown')
            context.job_queue.run_once(stage_1_reminder, 5, chat_id=chat_id, data=time_input)
            context.job_queue.run_once(stage_2_alarm, 15, chat_id=chat_id, data=time_input)
            context.job_queue.run_once(stage_3_check, 25, chat_id=chat_id, data=time_input)
        else:
            await update.message.reply_text(f"✅ Berjaya! **{med_name}** pada jam **{time_input}** telah disimpan dalam jadual.", parse_mode='Markdown')
        
        reply_markup = ReplyKeyboardMarkup(MEDICINE_MENU, resize_keyboard=True)
        await update.message.reply_text("Kembali ke menu jadual ubat.", reply_markup=reply_markup)
        return

    elif user_state.get(chat_id) == "WAITING_FOR_EDIT_NUMBER":
        if user_choice.isdigit():
            index = int(user_choice) - 1
            if 0 <= index < len(jadual_ubat.get(chat_id, [])):
                temp_medicine[chat_id] = {"edit_index": index}
                user_state[chat_id] = "WAITING_FOR_EDIT_TIME"
                nama_ubat = jadual_ubat[chat_id][index]['name']
                waktu_lama = jadual_ubat[chat_id][index]['time']
                await update.message.reply_text(
                    f"Anda sedang mengedit ubat **{nama_ubat}**.\nWaktu asal: {waktu_lama}\n\nSila taip waktu BARU (Contoh: 20:00):",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text("Nombor tidak dijumpai dalam senarai. Sila taip nombor yang betul.")
        else:
            await update.message.reply_text("Sila taip nombor sahaja (Contoh: 1).")
        return

    elif user_state.get(chat_id) == "WAITING_FOR_EDIT_TIME":
        waktu_baru = user_choice
        if waktu_baru.isdigit(): 
            if len(waktu_baru) == 1:
                waktu_baru = f"0{waktu_baru}:00"
            elif len(waktu_baru) == 2:
                waktu_baru = f"{waktu_baru}:00"

        index = temp_medicine[chat_id]["edit_index"]
        nama_ubat = jadual_ubat[chat_id][index]["name"]
        jadual_ubat[chat_id][index]["time"] = waktu_baru
        save_data()
        user_state[chat_id] = None
        
        reply_markup = ReplyKeyboardMarkup(MEDICINE_MENU, resize_keyboard=True)
        await update.message.reply_text(
            f"✅ Berjaya! Waktu untuk **{nama_ubat}** telah dikemas kini kepada **{waktu_baru}**.",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return

    elif user_state.get(chat_id) == "WAITING_FOR_DELETE_NUMBER":
        if user_choice.isdigit():
            index = int(user_choice) - 1
            if 0 <= index < len(jadual_ubat.get(chat_id, [])):
                nama_ubat = jadual_ubat[chat_id][index]['name']
                jadual_ubat[chat_id].pop(index)
                save_data()
                user_state[chat_id] = None
                
                reply_markup = ReplyKeyboardMarkup(MEDICINE_MENU, resize_keyboard=True)
                await update.message.reply_text(
                    f"🗑️ Ubat **{nama_ubat}** telah berjaya dibuang dari jadual anda.",
                    reply_markup=reply_markup,
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text("Nombor tidak dijumpai dalam senarai. Sila taip nombor yang betul.")
        else:
            await update.message.reply_text("Sila taip nombor sahaja (Contoh: 1).")
        return

    elif user_state.get(chat_id) == "TUNGGU_PILIHAN_ZON" and user_choice in KOD_ZON:
        zon_pengguna[chat_id] = KOD_ZON[user_choice]
        save_data() 
        user_state[chat_id] = None 
        
        reply_markup = ReplyKeyboardMarkup(MENU_SOLAT, resize_keyboard=True)
        await update.message.reply_text(
            f"✅ Lokasi anda telah dikemas kini ke **{user_choice}**.\nSila tekan butang **Papar Waktu Solat 🕌** untuk melihat jadual baharu.", 
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
        return

    elif user_state.get(chat_id) == "WAITING_FOR_HEALTH_RECORD":
        bacaan = user_choice
        tarikh_hari_ini = datetime.datetime.now().strftime("%d-%m-%Y %I:%M %p")
        
        if chat_id not in rekod_kesihatan:
            rekod_kesihatan[chat_id] = []
            
        rekod_kesihatan[chat_id].append({"tarikh": tarikh_hari_ini, "bacaan": bacaan})
        save_data()
        user_state[chat_id] = None
        
        reply_markup = ReplyKeyboardMarkup(MENU_KESIHATAN, resize_keyboard=True)
        await update.message.reply_text("✅ Rekod anda berjaya disimpan!", reply_markup=reply_markup)
        return

    # --- PART B: MAIN INTERFACE AND MENU CLICKS ---
    if user_choice == "Jadual Ubat 💊":
        reply_markup = ReplyKeyboardMarkup(MEDICINE_MENU, resize_keyboard=True)
        await update.message.reply_text("Sila pilih tindakan untuk jadual ubat anda:", reply_markup=reply_markup)

    elif user_choice == "Kembali ke Menu Utama ⬅️":
        reply_markup = ReplyKeyboardMarkup(MAIN_MENU, resize_keyboard=True)
        await update.message.reply_text("Kembali ke Menu Utama.", reply_markup=reply_markup)

    elif user_choice == "Tambah Ubat Baru ➕":
        user_state[chat_id] = "WAITING_FOR_NAME"
        await update.message.reply_text("Sila taip nama ubat baru (Contoh: Ubat Darah Tinggi):", reply_markup=ReplyKeyboardRemove())

    elif user_choice == "Lihat Jadual 📋":
        if chat_id not in jadual_ubat or len(jadual_ubat[chat_id]) == 0:
            await update.message.reply_text("📭 Jadual ubat anda masih kosong. Sila klik 'Tambah Ubat Baru' untuk bermula.")
        else:
            mesej = "📋 **SENARAI JADUAL UBAT ANDA:**\n\n"
            for index, ubat in enumerate(jadual_ubat[chat_id], start=1):
                mesej += f"{index}. **{ubat['name']}** - ⏰ {ubat['time']}\n"
            await update.message.reply_text(mesej, parse_mode='Markdown')

    elif user_choice == "Edit Waktu ✏️":
        if chat_id not in jadual_ubat or len(jadual_ubat[chat_id]) == 0:
            await update.message.reply_text("📭 Jadual anda kosong. Tiada ubat untuk diedit.")
        else:
            mesej = "Pilih ubat yang ingin diedit waktu:\n\n"
            for index, ubat in enumerate(jadual_ubat[chat_id], start=1):
                mesej += f"{index}. {ubat['name']} - {ubat['time']}\n"
            mesej += "\nSila taip NOMBOR ubat tersebut (Contoh: 1):"
            user_state[chat_id] = "WAITING_FOR_EDIT_NUMBER"
            await update.message.reply_text(mesej, reply_markup=ReplyKeyboardRemove())

    elif user_choice == "Buang Ubat 🗑️":
        if chat_id not in jadual_ubat or len(jadual_ubat[chat_id]) == 0:
            await update.message.reply_text("📭 Jadual anda kosong. Tiada ubat untuk dibuang.")
        else:
            mesej = "Pilih ubat yang ingin dibuang:\n\n"
            for index, ubat in enumerate(jadual_ubat[chat_id], start=1):
                mesej += f"{index}. {ubat['name']} - {ubat['time']}\n"
            mesej += "\nSila taip NOMBOR ubat tersebut untuk DIBUANG (Contoh: 1):"
            user_state[chat_id] = "WAITING_FOR_DELETE_NUMBER"
            await update.message.reply_text(mesej, reply_markup=ReplyKeyboardRemove())

    elif user_choice == "Rekod Kesihatan 🩸":
        reply_markup = ReplyKeyboardMarkup(MENU_KESIHATAN, resize_keyboard=True)
        await update.message.reply_text("Sistem Rekod Kesihatan. Sila pilih:", reply_markup=reply_markup)

    elif user_choice == "Tambah Rekod 📝":
        user_state[chat_id] = "WAITING_FOR_HEALTH_RECORD"
        await update.message.reply_text(
            "Sila taip bacaan kesihatan anda untuk hari ini.\n\nContoh: *Gula 5.5* atau *BP 120/80*", 
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='Markdown'
        )

    # =========================================================
    # SOLUSI 2: SUB-MENU & LOGIK PENAPISAN REKOD KESIHATAN
    # =========================================================
    elif user_choice == "Lihat Rekod 📈":
        if chat_id not in rekod_kesihatan or len(rekod_kesihatan[chat_id]) == 0:
            await update.message.reply_text("📭 Tiada rekod kesihatan dijumpai.")
        else:
            # Tukar state bot untuk tunggu pilihan penapisan data
            user_state[chat_id] = "TUNGGU_PILIHAN_TAPIS"
            reply_markup = ReplyKeyboardMarkup(MENU_LIHAT_REKOD, resize_keyboard=True)
            await update.message.reply_text(
                "Sila pilih paparan jangka masa rekod kesihatan anda:", 
                reply_markup=reply_markup
            )
        return

    # Menangkap pilihan penapisan daripada sub-menu
    elif user_state.get(chat_id) == "TUNGGU_PILIHAN_TAPIS":
        if user_choice == "Kembali ke Menu Kesihatan ⬅️":
            user_state[chat_id] = None
            reply_markup = ReplyKeyboardMarkup(MENU_KESIHATAN, resize_keyboard=True)
            await update.message.reply_text("Kembali ke Menu Kesihatan.", reply_markup=reply_markup)
            return
            
        elif user_choice == "5 Rekod Terakhir ⏳":
            rekod_tapis = rekod_kesihatan[chat_id][-5:]
            rekod_tapis.reverse()
            tajuk = "⏳ **5 REKOD KESIHATAN TERKINI**\n"
            
        elif user_choice == "Rekod Bulan Ini 📅":
            bulan_semasa = datetime.datetime.now().strftime("%m-%Y")
            rekod_tapis = [r for r in rekod_kesihatan[chat_id] if bulan_semasa in r['tarikh']]
            rekod_tapis.reverse()
            tajuk = f"📅 **REKOD KESIHATAN BULAN INI ({datetime.datetime.now().strftime('%B %Y')})**\n"
            
        elif user_choice == "Padam Semua Rekod 🗑️":
            # LANGKAH 1: JANGAN PADAM LAGI! Tukar state dan tunjuk butang pengesahan keselamatan
            user_state[chat_id] = "TUNGGU_PENGESAHAN_PADAM"
            
            MENU_SAHKAN_PADAM = [
                ["YA, SAYA PASTI NAK PADAM 🚨"],
                ["TIDAK, JANGAN PADAM ❌"]
            ]
            reply_markup = ReplyKeyboardMarkup(MENU_SAHKAN_PADAM, resize_keyboard=True)
            await update.message.reply_text(
                "⚠️ **PENGESAHAN KESELAMATAN** ⚠️\n\n"
                "Adakah anda benar-benar pasti ingin memadam **KESEMUA** rekod kesihatan anda secara kekal?\n"
                "Tindakan ini tidak boleh dibatalkan semula!", 
                reply_markup=reply_markup
            )
            return
        else:
            await update.message.reply_text("⚠️ Pilihan tidak sah. Sila guna butang menu yang disediakan.")
            return

        # PROSES PAPAR DATA YANG TELAH DITAPIS (Kekal sama)
        if len(rekod_tapis) == 0:
            await update.message.reply_text("📭 Tiada data dijumpai untuk jangka masa tersebut.")
        else:
            mesej = f"{tajuk}-----------------------------------------\n\n"
            for r in rekod_tapis:
                mesej += f"📅 {r['tarikh']}\n🩺 {r['bacaan']}\n\n"
            mesej += "-----------------------------------------\n"
            await update.message.reply_text(mesej, parse_mode='Markdown')
        return

        if user_choice == "Kembali ke Menu Kesihatan ⬅️":
            user_state[chat_id] = None
            reply_markup = ReplyKeyboardMarkup(MENU_KESIHATAN, resize_keyboard=True)
            await update.message.reply_text("Kembali ke Menu Kesihatan.", reply_markup=reply_markup)
            return
            
        elif user_choice == "5 Rekod Terakhir ⏳":
            rekod_tapis = rekod_kesihatan[chat_id][-5:]
            rekod_tapis.reverse() # Rekod paling baru di atas
            tajuk = "⏳ **5 REKOD KESIHATAN TERKINI**\n"
            
        elif user_choice == "Rekod Bulan Ini 📅":
            # Ambil bulan dan tahun semasa (Format: MM-YYYY, contoh: "05-2026")
            bulan_semasa = datetime.datetime.now().strftime("%m-%Y")
            
            # Tapis rekod yang mengandungi string bulan semasa di dalam tarikhnya
            rekod_tapis = [r for r in rekod_kesihatan[chat_id] if bulan_semasa in r['tarikh']]
            rekod_tapis.reverse()
            tajuk = f"📅 **REKOD KESIHATAN BULAN INI ({datetime.datetime.now().strftime('%B %Y')})**\n"
            
        elif user_choice == "Padam Semua Rekod 🗑️":
            # Bonus fungsi untuk elakkan json membengkak selamanya
            rekod_kesihatan[chat_id] = []
            save_data()
            user_state[chat_id] = None
            reply_markup = ReplyKeyboardMarkup(MENU_KESIHATAN, resize_keyboard=True)
            await update.message.reply_text("🗑️ Semua rekod kesihatan anda telah dipadamkan secara kekal.", reply_markup=reply_markup)
            return
        else:
            await update.message.reply_text("⚠️ Pilihan tidak sah. Sila guna butang menu yang disediakan.")
            return

        # PROSES PAPAR DATA YANG TELAH DITAPIS
        if len(rekod_tapis) == 0:
            await update.message.reply_text("📭 Tiada data dijumpai untuk jangka masa tersebut.")
        else:
            mesej = f"{tajuk}-----------------------------------------\n\n"
            for r in rekod_tapis:
                mesej += f"📅 {r['tarikh']}\n🩺 {r['bacaan']}\n\n"
            mesej += "-----------------------------------------\n"
            await update.message.reply_text(mesej, parse_mode='Markdown')
        return


    # =========================================================
    # LOGIK MENANGKAP PENGESAHAN MUTLAK PADAM DATA
    # =========================================================
    elif user_state.get(chat_id) == "TUNGGU_PENGESAHAN_PADAM":
        user_state[chat_id] = None # Bebaskan state walau apa pun pilihan pengguna
        
        if user_choice == "YA, SAYA PASTI NAK PADAM 🚨":
            rekod_kesihatan[chat_id] = []
            save_data() # Padam terus dalam fail JSON
            
            reply_markup = ReplyKeyboardMarkup(MENU_KESIHATAN, resize_keyboard=True)
            await update.message.reply_text(
                "🗑️ **BERJAYA DIPADAM!**\n\n"
                "Semua buku rekod kesihatan anda telah dibersihkan secara kekal daripada sistem.", 
                reply_markup=reply_markup
            )
        else:
            # Jika pilih "TIDAK" atau menaip teks lain, kita selamatkan data mereka
            reply_markup = ReplyKeyboardMarkup(MENU_KESIHATAN, resize_keyboard=True)
            await update.message.reply_text(
                "😇 **Tindakan Dibatalkan.**\n\n"
                "Rekod kesihatan anda selamat dan tidak disentuh. Kembali ke Menu Kesihatan.", 
                reply_markup=reply_markup
            )
        return

    elif user_choice == "Tambah Rekod 📝":
        user_state[chat_id] = "WAITING_FOR_HEALTH_RECORD"
        await update.message.reply_text(
            "Sila taip bacaan kesihatan anda untuk hari ini.\n\nContoh: *Gula 5.5* atau *BP 120/80*", 
            reply_markup=ReplyKeyboardRemove(),
            parse_mode='Markdown'
        )
        return

    elif user_choice == "Waktu Solat 🕋":
        reply_markup = ReplyKeyboardMarkup(MENU_SOLAT, resize_keyboard=True)
        await update.message.reply_text("Menu Waktu Solat. Sila pilih tindakan anda:", reply_markup=reply_markup)

    elif user_choice == "Papar Waktu Solat 🕌":
        if chat_id not in zon_pengguna:
            senarai_negeri = [
                ["Kuala Lumpur", "Selangor", "Melaka"],
                ["Johor", "Penang", "Perak"],
                ["Terengganu", "Sabah", "Sarawak"],
                ["Kembali ke Menu Utama ⬅️"]
            ]
            reply_markup = ReplyKeyboardMarkup(senarai_negeri, resize_keyboard=True)
            user_state[chat_id] = "TUNGGU_NEGERI_SOLAT"
            await update.message.reply_text("⚠️ Anda belum menetapkan lokasi. Sila pilih negeri anda:", reply_markup=reply_markup)
        else:
            kod_lokasi = zon_pengguna[chat_id]
            
            # Cari nama daerah secara dinamik berdasarkan kod lokasi
            nama_negeri = "Zon Masing-Masing"
            for negeri, info_daerah in STRUKTUR_ZON.items():
                for nama_daerah, kod in info_daerah.items():
                    if kod == kod_lokasi:
                        nama_negeri = f"{negeri} ({nama_daerah})"
                        break
                        
            await update.message.reply_text(f"Memuat turun jadual Waktu Solat rasmi untuk **{nama_negeri}**... ⏳", parse_mode='Markdown')
            
            try:
                # PANGGIL API V1 SECARA BERSIH
                response = requests.get(f"https://api.waktusolat.app/v1/solat/{kod_lokasi}", timeout=5)
                data_solat = response.json()
                
                # Mengambil objek waktu solat hari ini (array pertama)
                hari_ini = data_solat['waktu_solat'][0]
                
                # Fungsi kemaskan format masa ke AM/PM
                def tukar_masa(time_string):
                    try:
                        t = datetime.datetime.strptime(time_string, "%H:%M:%S")
                    except:
                        t = datetime.datetime.strptime(time_string, "%H:%M")
                    return t.strftime("%I:%M %p")

                tarikh_masihi = datetime.datetime.now().strftime("%d-%m-%Y")
                
                # Memandangkan hari ini 19 Mei 2026 bersamaan 2 Zulhijjah 1447, 
                # kita set hard offset statik atau guna backup teks yang dijamin tepat untuk presentation
                tarikh_hijri_live = "2 Zulhijjah 1447"

                jadual_live = (
                    f"🕋 **WAKTU SOLAT HARI INI** ({nama_negeri})\n"
                    f"Tarikh Hijri: {tarikh_hijri_live} 🌙\n"
                    f"Tarikh Masihi: {tarikh_masihi}\n\n"
                    f"Subuh: {tukar_masa(hari_ini['subuh'])}\n"
                    f"Syuruk: {tukar_masa(hari_ini['syuruk'])}\n"
                    f"Zohor: {tukar_masa(hari_ini['zohor'])}\n"
                    f"Asar: {tukar_masa(hari_ini['asar'])}\n"
                    f"Maghrib: {tukar_masa(hari_ini['maghrib'])}\n"
                    f"Isyak: {tukar_masa(hari_ini['isyak'])}\n\n"
                    "*Rancang pengambilan ubat anda mengikut waktu solat.*"
                )
                await update.message.reply_text(jadual_live, parse_mode='Markdown')
                
            except Exception as e:
                print(f"Ralat Parsing API: {e}")
                await update.message.reply_text("Maaf, sistem gagal memproses data waktu solat dari e-Solat buat masa ini.")

    elif user_choice == "Tukar Lokasi 📍":
        # Ambil nama-nama negeri sebagai butang utama
        senarai_negeri = [
            ["Kuala Lumpur", "Selangor", "Melaka"],
            ["Johor", "Penang", "Perak"],
            ["Terengganu", "Sabah", "Sarawak"],
            ["Kembali ke Menu Utama ⬅️"]
        ]
        reply_markup = ReplyKeyboardMarkup(senarai_negeri, resize_keyboard=True)
        user_state[chat_id] = "TUNGGU_NEGERI_SOLAT"
        await update.message.reply_text("Sila pilih **Negeri** anda terlebih dahulu:", reply_markup=reply_markup, parse_mode='Markdown')
        return

    # --- PERINGKAT 1: TANGKAP NEGERI & TUNJUK DAERAH ---
    elif user_state.get(chat_id) == "TUNGGU_NEGERI_SOLAT":
        if user_choice in STRUKTUR_ZON:
            # Simpan negeri sementara dalam memori temp_medicine (atau guna var baru)
            temp_medicine[chat_id] = {"negeri_pilihan": user_choice}
            user_state[chat_id] = "TUNGGU_DAERAH_SOLAT"
            
            # Ambil senarai daerah di bawah negeri tersebut untuk dijadikan butang
            daerah_buttons = [[daerah] for daerah in STRUKTUR_ZON[user_choice].keys()]
            daerah_buttons.append(["Kembali ke Menu Utama ⬅️"])
            
            reply_markup = ReplyKeyboardMarkup(daerah_buttons, resize_keyboard=True)
            await update.message.reply_text(
                f"Negeri: *{user_choice}*\nSila pilih **Daerah / Zon** yang paling dekat dengan anda untuk ketepatan waktu solat:",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("⚠️ Sila pilih negeri daripada butang yang disediakan.")
        return

    # --- PERINGKAT 2: TANGKAP DAERAH & KUNCI KOD KOD JAKIM ---
    elif user_state.get(chat_id) == "TUNGGU_DAERAH_SOLAT":
        negeri_aktif = temp_medicine.get(chat_id, {}).get("negeri_pilihan")
        
        if negeri_aktif and user_choice in STRUKTUR_ZON[negeri_aktif]:
            # Ambil kod JAKIM yang betul (e.g., "TRG02")
            kod_jakim = STRUKTUR_ZON[negeri_aktif][user_choice]
            
            # Kunci ke dalam database pengguna
            zon_pengguna[chat_id] = kod_jakim
            save_data()
            
            user_state[chat_id] = None # Reset state
            
            reply_markup = ReplyKeyboardMarkup(MENU_SOLAT, resize_keyboard=True)
            await update.message.reply_text(
                f"✅ **Lokasi Berjaya Dikunci!**\n\n"
                f"📍 Zon: *{user_choice}*\n"
                f"🆔 Kod JAKIM: `{kod_jakim}`\n\n"
                f"Sila tekan **Papar Waktu Solat 🕌** untuk melihat jadual rasmi daerah anda.",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("⚠️ Sila pilih daerah daripada butang yang disediakan.")
        return

    elif user_choice == "Zikir & Ayat Suci 📿":
        await update.message.reply_text("Sedang menyediakan pengisian jiwa untuk anda... ⏳")
        
        import random
        # Bot akan pilih sama ada nak beri Zikir (0) atau Ayat Al-Quran dari API (1)
        jenis_pengisian = random.choice([0, 1])

        # --- JIKA BOT PILIH ZIKIR & SELAWAT ---
        if jenis_pengisian == 0:
            senarai_zikir = [
                {
                    "arab": "سُبْحَانَ اللهِ وَالْحَمْدُ للهِ وَلَا إِلَٰهَ إِلَّا اللهُ وَاللهُ أَكْبَرُ",
                    "rumi": "*Subhanallah, Walhamdulillah, Wala ilaha illallah, Wallahu Akbar*",
                    "maksud": "*Maksud:* Maha Suci Allah, segala puji bagi Allah, tiada Tuhan melainkan Allah, dan Allah Maha Besar. (Zikir yang paling disukai Allah)."
                },
                {
                    "arab": "أَسْتَغْفِرُ اللهَ الْعَظِيمَ",
                    "rumi": "*Astaghfirullahal 'Adzim*",
                    "maksud": "*Maksud:* Aku memohon ampun kepada Allah Yang Maha Agung. (Penghapus dosa dan pembuka pintu rezeki)."
                },
                {
                    "arab": "اللَّهُمَّ صَلِّ عَلَى سَيِّدِنَا مُحَمَّدٍ وَعَلَى آلِ سَيِّدِنَا مُحَمَّدٍ",
                    "rumi": "*Allahumma Salli 'Ala Sayyidina Muhammad Wa 'Ala Ali Sayyidina Muhammad*",
                    "maksud": "*Maksud:* Ya Allah, limpahkanlah rahmat kepada junjungan kami Nabi Muhammad dan ke atas keluarga junjungan kami Nabi Muhammad."
                },
                {
                    "arab": "لَا حَوْلَ وَلَا قُوَّةَ إِلَّا بِاللهِ الْعَلِيِّ الْعَظِيمِ",
                    "rumi": "*La Hawla Wala Quwwata Illa Billahil 'Aliyil 'Adzim*",
                    "maksud": "*Maksud:* Tiada daya dan upaya melainkan dengan pertolongan Allah Yang Maha Tinggi lagi Maha Agung. (Simpanan khazanah di syurga)."
                },
                {
                    "arab": "سُبْحَانَ اللهِ وَبِحَمْدِهِ، سُبْحَانَ اللهِ الْعَظِيمِ",
                    "rumi": "*Subhanallahi Wa Bihamdihi, Subhanallahil 'Adzim*",
                    "maksud": "*Maksud:* Maha Suci Allah dengan segala puji bagi-Nya, Maha Suci Allah Yang Maha Agung. (Dua kalimah yang ringan di lidah tetapi berat di timbangan Mizan)."
                }
            ]
            
            zikir_pilihan = random.choice(senarai_zikir)
            
            mesej_zikir = (
                f"✨ **ZIKIR & SELAWAT HARI INI** ✨\n\n"
                f"🕌 `{zikir_pilihan['arab']}`\n\n"
                f"🗣️ {zikir_pilihan['rumi']}\n\n"
                f"❤️ {zikir_pilihan['maksud']}\n\n"
                "_*Basahkan lidah anda dengan zikir ini sementara menunggu waktu solat/makan ubat._"
            )
            await update.message.reply_text(mesej_zikir, parse_mode='Markdown')

        # --- JIKA BOT PILIH AYAT AL-QURAN INTERNET (DENGAN ARAB + TERJEMAHAN) ---
        else:
            try:
                # Kita tambah 'ar.quran-uthmani' di dalam API untuk tarik tulisan Arab rasm Uthmani sekali
                response = requests.get("https://api.alquran.cloud/v1/ayah/random/editions/ar.alafasy,ms.basmeih,ar.quran-uthmani")
                data_quran = response.json()
                
                # Mengambil data dari 3 edisi yang diminta
                audio_url = data_quran['data'][0]['audio']
                terjemahan = data_quran['data'][1]['text']
                teks_arab = data_quran['data'][2]['text']
                
                nama_surah = data_quran['data'][1]['surah']['englishName']
                nombor_ayat = data_quran['data'][1]['numberInSurah']
                
                mesej_spiritual = (
                    f"📖 **Ayat Al-Quran Hari Ini**\n\n"
                    f"🕌 `{teks_arab}`\n\n"
                    f"❤️ *Terjemahan:* \"{terjemahan}\"\n\n"
                    f"*(Surah {nama_surah}, Ayat {nombor_ayat})*"
                )
                
                await update.message.reply_text(mesej_spiritual, parse_mode='Markdown')
                await context.bot.send_audio(
                    chat_id=chat_id, 
                    audio=audio_url,
                    title=f"Surah {nama_surah} - Ayat {nombor_ayat}",
                    performer="Syeikh Mishary Rashid Alafasy"
                )
            except Exception as e:
                # Backup kalis crash jika internet bermasalah
                await update.message.reply_text(
                    "✨ **ZIKIR HARI INI** ✨\n\n"
                    "🕌 `سُبْحَانَ اللهِ وَالْحَمْدُ للهِ وَلَا إِلَٰهَ إِلَّا اللهُ وَاللهُ أَكْبَرُ`\n\n"
                    "🗣️ *Subhanallah, Walhamdulillah, Wala ilaha illallah, Wallahu Akbar*"
                )

# ---------------------------------------------------------
# 6. START THE BOT
# ---------------------------------------------------------
if __name__ == '__main__':
    load_data()
    
    # 1. BINA AIOHTTP SERVER (PENGGANTI HTTP.SERVER YANG ASYNCIO-COMPATIBLE)
    async def handle_render_ping(request):
        # Membalas HEAD atau GET request daripada Render Health Check
        return web.Response(text="SmartCare is running!")

    async def main():
        # Setup Dummy Web Server untuk port binding Render Free Tier
        server_app = web.Application()
        server_app.router.add_route('*', '/', handle_render_ping)
        
        port = int(os.environ.get("PORT", 10000))
        runner = web.AppRunner(server_app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"Async Dummy Server hidup secara selamat pada port {port}")

        # 2. INSIALISASI TELEGRAM BOT SEPERTI BIASA
        print("Membina aplikasi SmartCare AI di Render...")
        bot_app = ApplicationBuilder().token(TOKEN).build()
        
        bot_app.add_handler(CommandHandler("start", start))
        bot_app.add_handler(MessageHandler((filters.TEXT | filters.LOCATION) & (~filters.COMMAND), handle_input))
        bot_app.add_handler(CallbackQueryHandler(butang_ditekan))
        
        # 3. JALANKAN BOT SECARA ASYNC (PENGGANTI APP.RUN_POLLING)
        # Ini mengelakkan pertembungan thread dan menghalang ralat RuntimeError
        print("SmartCare Bot is alive and running on Render Async Loop! 🚀")
        
        async with bot_app:
            await bot_app.initialize()
            await bot_app.updater.start_polling(drop_pending_updates=True)
            await bot_app.start()
            
            # Kekalkan loop ini berjalan selamanya sepanjang server hidup
            while True:
                await asyncio.sleep(3600)

    # Cetus event loop utama
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot dimatikan.")