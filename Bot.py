import asyncio
import sqlite3
import logging
import os
import shutil
from dotenv import load_dotenv
load_dotenv()
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

# --- LOGGING ---
logging.basicConfig(level=logging.INFO)

# --- SOZLAMALAR ---
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN muhit o'zgaruvchisi o'rnatilmagan! .env faylni tekshiring.")
bot = Bot(token=TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- FSM HOLATLAR ---
class LoginState(StatesGroup):
    id_kutish = State()
    parol_kutish = State()

class AdminClearState(StatesGroup):
    parol_kutish = State()
    tasdiqlash = State()

class BichuvState(StatesGroup):
    nomi = State()
    kodi = State()
    razmer_tanlash = State()
    soni_kutish = State()
    tasdiqlash = State()

class NarxState(StatesGroup):
    bichuv_id = State()
    summa = State()

class RazdachaState(StatesGroup):
    target_ch = State()
    model_tanlash = State()
    razmer_tanlash = State()
    soni = State()
    tasdiqlash = State()

class ChevarState(StatesGroup):
    ish_tanlash = State()
    topshirish_soni = State()

class ChevarQaytarishState(StatesGroup):
    ish_tanlash = State()
    miqdor      = State()
    sabab       = State()

# --- DATABASE ---
def init_db():
    conn = sqlite3.connect("fabrika.db")
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    # Hodimlar jadvaliga 'sana' ustuni qo'shildi
    cursor.execute('''CREATE TABLE IF NOT EXISTS hodimlar (
        id INTEGER PRIMARY KEY, 
        parol TEXT, 
        ism TEXT, 
        rol TEXT, 
        chat_id INTEGER,
        sana TEXT DEFAULT CURRENT_TIMESTAMP)''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS bichuv_ombor (id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT, kod TEXT, razmer TEXT, soni INTEGER, status INTEGER DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS razdacha_ombor (id INTEGER PRIMARY KEY AUTOINCREMENT, model TEXT, kod TEXT, razmer TEXT, soni INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS ishlar (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        model TEXT, kod TEXT, razmer TEXT, 
        umumiy_soni INTEGER, 
        qolgan_soni INTEGER, 
        topshirildi_soni INTEGER DEFAULT 0,
        chevar_id INTEGER, 
        status TEXT, 
        vaqt TEXT)''')
        
    cursor.execute('''CREATE TABLE IF NOT EXISTS bitgan_ishlar (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vaqt TEXT, chevar_id INTEGER,
        model_nomi TEXT, kodi TEXT, razmer TEXT,
        soni INTEGER, holat TEXT, sana TEXT
    )''')
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS tariflar (
        bichuv_id TEXT PRIMARY KEY,
        narx INTEGER DEFAULT 0)''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS qaytarish_sorovi (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ish_id INTEGER,
        chevar_id INTEGER,
        miqdor INTEGER,
        sabab TEXT,
        vaqt TEXT,
        holat TEXT DEFAULT 'ochiq'
    )''')

    # Mavjud bazaga yangi ustunlar qo'shish (xavfsiz)
    for migration in [
        "ALTER TABLE hodimlar ADD COLUMN sana TEXT DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE ishlar ADD COLUMN biriktirgan_id INTEGER",
        "ALTER TABLE ishlar ADD COLUMN qabul_vaqt TEXT",
        "ALTER TABLE ishlar ADD COLUMN rad_sababi TEXT",
    ]:
        try:
            cursor.execute(migration)
        except sqlite3.OperationalError:
            pass

    users = [
        (445178136, 'admin710', 'Boshliq', 'admin'), 
        (701, 'razdacha701', 'Razdacha 701', 'razdacha'), 
        (705, 'bichuv705', 'Bichuvchi 705', 'bichuvchi')
    ]
    for i in range(101, 201): 
        users.append((i, f"chevar{i}", f"Chevar {i}", "chevar"))
        
    cursor.executemany("INSERT OR IGNORE INTO hodimlar (id, parol, ism, rol) VALUES (?,?,?,?)", users)
    conn.commit()
    conn.close()

# --- KLAVIATURALAR ---
def get_main_menu(rol, user_id=None):
    kb = ReplyKeyboardBuilder()
    if rol == 'admin':
        kb.row(types.KeyboardButton(text="📊 Kunlik malumotlar"), types.KeyboardButton(text="📋 Hodimlar ruyxati"))
        kb.row(types.KeyboardButton(text="💰 Narx belgilash")) # <--- Admin uchun narx tugmasi
        if user_id == 445178136:
            kb.row(types.KeyboardButton(text="🗑 Bazani tozalash"))
    elif rol == 'bichuvchi':
        kb.row(types.KeyboardButton(text="✂️ Bichildi"), types.KeyboardButton(text="🚚 Razdachaga ish yuborish"))
    elif rol == 'razdacha':
        kb.row(types.KeyboardButton(text="📥 Bichuvdan ish olish"), types.KeyboardButton(text="✂️ Chevarga ish berish"))
        kb.row(types.KeyboardButton(text="🏁 Chevardan ish olish"), types.KeyboardButton(text="📦 Ombor holati"))
        kb.row(types.KeyboardButton(text="⏳ Kutilayotgan ishlar")) 
        kb.row(types.KeyboardButton(text="🧵 Tikuvdagi topshiriqlar"), types.KeyboardButton(text="📜 Bitgan ishlar tarixi"))
    elif rol == 'chevar':
        kb.row(types.KeyboardButton(text="📥 Qabul uchun ishlar"), types.KeyboardButton(text="🧵 Tikilayotgan ishlar"))
        kb.row(types.KeyboardButton(text="📤 Ish topshirish"), types.KeyboardButton(text="↩️ Ish qaytarish"))
        kb.row(types.KeyboardButton(text="💰 Mening balansim"))
    
    kb.row(types.KeyboardButton(text="🏠 Asosiy sahifa"), types.KeyboardButton(text="🚪 Profildan chiqish"))
    return kb.as_markup(resize_keyboard=True)

def back_kb():
    return ReplyKeyboardBuilder().row(types.KeyboardButton(text="🏠 Asosiy sahifa")).as_markup(resize_keyboard=True)

# --- ASOSIY FUNKSIYALAR ---
@dp.message(Command("start"), StateFilter("*")) 
async def cmd_start(m: types.Message, state: FSMContext):
    await state.clear()
    await state.set_state(LoginState.id_kutish)
    await m.answer("🏭 **A Tex Sanoat Tizimi**\n\n🆔 **ID raqamingizni kiriting:**", parse_mode="Markdown")

@dp.message(F.text == "🏠 Asosiy sahifa", StateFilter("*"))
async def back_to_main(m: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("fabrika.db")
    user = conn.execute("SELECT rol FROM hodimlar WHERE chat_id=?", (m.from_user.id,)).fetchone()
    conn.close()
    if user:
        await m.answer("🏠 Asosiy menyu:", reply_markup=get_main_menu(user[0], m.from_user.id))
    else:
        await cmd_start(m, state)

@dp.message(F.text == "🚪 Profildan chiqish", StateFilter("*"))
async def logout(m: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("fabrika.db")
    conn.execute("UPDATE hodimlar SET chat_id=NULL WHERE chat_id=?", (m.from_user.id,))
    conn.commit()
    conn.close()
    await m.answer("Hisobdan chiqildi. /start", reply_markup=types.ReplyKeyboardRemove())

@dp.message(LoginState.id_kutish)
async def login_id(m: types.Message, state: FSMContext):
    if not m.text.isdigit(): return await m.answer("⚠️ ID faqat raqam bo'ladi!")
    await state.update_data(uid=int(m.text))
    await state.set_state(LoginState.parol_kutish)
    await m.answer("🔑 **Parolingizni kiriting:**")

@dp.message(LoginState.parol_kutish)
async def login_pw(m: types.Message, state: FSMContext):
    d = await state.get_data()
    conn = sqlite3.connect("fabrika.db")
    user = conn.execute("SELECT ism, rol FROM hodimlar WHERE id=? AND parol=?", (d['uid'], m.text)).fetchone()
    if user:
        conn.execute("UPDATE hodimlar SET chat_id=? WHERE id=?", (m.from_user.id, d['uid']))
        conn.commit()
        await m.answer(f"✅ Xush kelibsiz, {user[0]}!", reply_markup=get_main_menu(user[1], m.from_user.id))
        await state.clear()
    else:
        await m.answer("❌ Parol yoki ID xato!")
    conn.close()

# --- ADMIN: HODIMLAR RO'YXATI (Sana ustunisiz variant) ---
@dp.message(F.text == "📋 Hodimlar ruyxati", StateFilter("*"))
async def admin_hodimlar_list(m: types.Message):
    conn = sqlite3.connect("fabrika.db")
    user = conn.execute("SELECT rol FROM hodimlar WHERE chat_id=?", (m.from_user.id,)).fetchone()
    if not user or user[0] != 'admin':
        conn.close()
        return await m.answer("⛔️ Faqat adminlar uchun!")

    cursor = conn.cursor()
    # Bu yerda 'sana' olib tashlandi
    cursor.execute("SELECT id, ism, rol, parol FROM hodimlar ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return await m.answer("📭 Hodimlar topilmadi.")

    await m.answer(f"📋 Jami hodimlar: {len(rows)} ta. Ro'yxat yuklanmoqda...")
    
    chunk_size = 20 
    for i in range(0, len(rows), chunk_size):
        chunk = rows[i:i + chunk_size]
        msg = "📂 **HODIMLAR RO'YXATI**\n\n"
        for r in chunk:
            msg += (f"🆔 ID: `{r[0]}` | 👤 **{r[1]}**\n"
                    f"💼 {r[2].upper()} | 🔑 `{r[3]}`\n"
                    f"------------------------\n")
        await m.answer(msg, parse_mode="Markdown")
        await asyncio.sleep(0.4)

# --- ADMIN: BAZANI TOZALASH ---
@dp.message(F.text == "🗑 Bazani tozalash", StateFilter("*"))
async def admin_clear_start(m: types.Message, state: FSMContext):
    if m.from_user.id == 445178136:
        await state.set_state(AdminClearState.parol_kutish)
        await m.answer("🚨 **DIQQAT: BAZANI TOZALASH**\nTasdiqlash kodini kiriting:", reply_markup=back_kb())

@dp.message(AdminClearState.parol_kutish)
async def admin_clear_password(m: types.Message, state: FSMContext):
    if m.text == "Mz12345":
        await state.set_state(AdminClearState.tasdiqlash)
        kb = ReplyKeyboardBuilder()
        kb.row(types.KeyboardButton(text="🔥 HA, HAMMASINI O'CHIRISH"))
        kb.row(types.KeyboardButton(text="🏠 Asosiy sahifa"))
        await m.answer("🛡 **Kod to'g'ri.**\nHamma narsa (ishlar, ombor, tarix) o'chsinmi?", 
                        reply_markup=kb.as_markup(resize_keyboard=True))
    elif m.text == "🏠 Asosiy sahifa":
        await back_to_main(m, state)
    else:
        await m.answer("❌ Kod xato!")

@dp.message(AdminClearState.tasdiqlash, F.text == "🔥 HA, HAMMASINI O'CHIRISH")
async def admin_db_execute(m: types.Message, state: FSMContext):
    if m.from_user.id != 445178136: return
    conn = sqlite3.connect("fabrika.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM ishlar")
    cursor.execute("DELETE FROM bitgan_ishlar")
    cursor.execute("DELETE FROM bichuv_ombor")
    cursor.execute("UPDATE razdacha_ombor SET soni = 0")
    conn.commit()
    conn.close()
    await m.answer("🚀 Baza tozalandi!", reply_markup=get_main_menu('admin', m.from_user.id))
    await state.clear()


# ================= BICHUV BO'LIMI =================
@dp.message(F.text == "✂️ Bichildi", StateFilter("*"))
async def bich_1(m: types.Message, state: FSMContext):
    await state.set_state(BichuvState.nomi)
    await m.answer("👗 Model nomi:", reply_markup=back_kb())

@dp.message(BichuvState.nomi)
async def bich_2(m: types.Message, state: FSMContext):
    await state.update_data(nomi=m.text, bichiqlar=[])
    await state.set_state(BichuvState.kodi)
    await m.answer("🔢 Bichuv kodi:")

@dp.message(BichuvState.kodi)
async def bich_3(m: types.Message, state: FSMContext):
    conn = sqlite3.connect("fabrika.db")
    if conn.execute("SELECT id FROM bichuv_ombor WHERE kod=?", (m.text,)).fetchone():
        conn.close()
        return await m.answer("❌ Bu kod bazada bor!")
    conn.close()
    await state.update_data(kodi=m.text)
    await ask_razmer(m, state)

async def ask_razmer(m: types.Message, state: FSMContext):
    data = await state.get_data()
    b_list = data.get('bichiqlar', [])
    used = [str(b['r']) for b in b_list]
    kb = ReplyKeyboardBuilder()
    for r in range(46, 60, 2):
        if str(r) not in used: kb.add(types.KeyboardButton(text=str(r)))
    kb.row(types.KeyboardButton(text="✅ Hammasi tugadi"), types.KeyboardButton(text="🏠 Asosiy sahifa"))
    kb.adjust(4, 2)
    await state.set_state(BichuvState.razmer_tanlash)
    await m.answer(f"📐 Model: {data['nomi']} ({data['kodi']})\nRazmer tanlang:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(BichuvState.razmer_tanlash)
async def bich_raz(m: types.Message, state: FSMContext):
    if m.text == "✅ Hammasi tugadi":
        data = await state.get_data()
        b_list = data.get('bichiqlar', [])
        if not b_list: return await m.answer("⚠️ Hech qanday razmer kiritilmadi!", reply_markup=get_main_menu('bichuvchi'))
        hisobot = f"📋 **Kiritilgan ma'lumotlarni tekshiring:**\n\n👗 Model: **{data['nomi']}**\n🔢 Kod: **{data['kodi']}**\n📏 Razmerlar:\n"
        jami_soni = 0
        for b in b_list:
            hisobot += f"   • {b['r']} razmer: {b['s']} ta\n"
            jami_soni += b['s']
        hisobot += f"\n💰 **Jami: {jami_soni} ta**\n\nMa'lumotlar to'g'rimi?"
        kb = ReplyKeyboardBuilder()
        kb.row(types.KeyboardButton(text="✅ Tasdiqlayman"), types.KeyboardButton(text="❌ Hammasini bekor qilish"))
        kb.row(types.KeyboardButton(text="➕ Yana qo'shish"))
        await state.set_state(BichuvState.tasdiqlash)
        return await m.answer(hisobot, parse_mode="Markdown", reply_markup=kb.as_markup(resize_keyboard=True))
    await state.update_data(current_raz=m.text)
    await state.set_state(BichuvState.soni_kutish)
    await m.answer(f"🔢 {m.text} razmerdan necha dona?")

@dp.message(BichuvState.soni_kutish)
async def bich_soni(m: types.Message, state: FSMContext):
    if not m.text.isdigit(): return await m.answer("Raqam yozing!")
    data = await state.get_data()
    b_list = data.get('bichiqlar', [])
    b_list.append({"r": data['current_raz'], "s": int(m.text)})
    await state.update_data(bichiqlar=b_list)
    await ask_razmer(m, state)

@dp.message(BichuvState.tasdiqlash)
async def bich_final_confirm(m: types.Message, state: FSMContext):
    if m.text == "✅ Tasdiqlayman":
        data = await state.get_data()
        conn = sqlite3.connect("fabrika.db")
        for b in data['bichiqlar']:
            conn.execute("INSERT INTO bichuv_ombor (model, kod, razmer, soni) VALUES (?,?,?,?)", (data['nomi'], data['kodi'], b['r'], b['s']))
        conn.commit()
        conn.close()
        await m.answer("✅ Omborga muvaffaqiyatli saqlandi!", reply_markup=get_main_menu('bichuvchi'))
        await state.clear()
    elif m.text == "➕ Yana qo'shish": await ask_razmer(m, state)
    elif m.text == "❌ Hammasini bekor qilish":
        await m.answer("🚫 Ma'lumotlar bekor qilindi.", reply_markup=get_main_menu('bichuvchi'))
        await state.clear()

@dp.message(F.text == "🚚 Razdachaga ish yuborish", StateFilter("*"))
async def bich_send(m: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("fabrika.db")
    items = conn.execute("SELECT kod, model, SUM(soni) FROM bichuv_ombor WHERE status=0 GROUP BY kod").fetchall()
    conn.close()
    if not items: return await m.answer("📭 Yangi ish yo'q.")
    for i in items:
        ikb = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="👁 Ko'rish va Uzatish", callback_data=f"b_view_{i[0]}"))
        await m.answer(f"📦 {i[1]} ({i[0]}) | {i[2]} ta", reply_markup=ikb.as_markup())

@dp.callback_query(F.data.startswith("b_view_"))
async def b_view_before_send(cb: types.CallbackQuery):
    kod = cb.data.replace("b_view_", "")
    conn = sqlite3.connect("fabrika.db")
    res = conn.execute("SELECT model, razmer, soni FROM bichuv_ombor WHERE kod=? AND status=0", (kod,)).fetchall()
    conn.close()
    if not res: return await cb.answer("❌ Ma'lumot topilmadi.", show_alert=True)
    txt = f"📝 **Yuborilayotgan ish tafsilotlari (Kod: {kod}):**\n👗 Model: {res[0][0]}\n\n"
    jami = sum(r[2] for r in res)
    for r in res: txt += f"🔹 R: {r[1]} — {r[2]} ta\n"
    txt += f"\n💰 **Jami: {jami} ta**\n\nRazdachaga yuborishni tasdiqlaysizmi?"
    ikb = InlineKeyboardBuilder()
    ikb.row(types.InlineKeyboardButton(text="✅ Ha, yuborilsin", callback_data=f"b_to_r_conf_{kod}"))
    ikb.row(types.InlineKeyboardButton(text="❌ Yo'q, bekor qilish", callback_data="b_cancel_send"))
    await cb.message.edit_text(txt, reply_markup=ikb.as_markup())

@dp.callback_query(F.data.startswith("b_to_r_conf_"))
async def b_to_r_confirm_cb(cb: types.CallbackQuery):
    kod = cb.data.replace("b_to_r_conf_", "")
    conn = sqlite3.connect("fabrika.db")
    conn.execute("UPDATE bichuv_ombor SET status=1 WHERE kod=?", (kod,))
    conn.commit()
    conn.close()
    await cb.message.edit_text(f"🚀 ✅ Kod {kod} Razdachaga muvaffaqiyatli yuborildi.")

@dp.callback_query(F.data == "b_cancel_send")
async def b_cancel_send_cb(cb: types.CallbackQuery):
    await cb.message.edit_text("🚫 Bekor qilindi.")

# ================= RAZDACHA BO'LIMI =================

@dp.message(F.text == "📥 Bichuvdan ish olish", StateFilter("*"))
async def raz_rec(m: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("fabrika.db")
    items = conn.execute("SELECT kod, model, SUM(soni) FROM bichuv_ombor WHERE status=1 GROUP BY kod").fetchall()
    conn.close()
    if not items: return await m.answer("📭 Kelgan ishlar yo'q.")
    for i in items:
        ikb = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="👁 Ko'rish va Qabul", callback_data=f"r_view_bichuv_{i[0]}"))
        await m.answer(f"📥 Yangi bichuv:\nModel: {i[1]}\nKod: {i[0]}\nJami: {i[2]} ta", reply_markup=ikb.as_markup())

@dp.callback_query(F.data.startswith("r_view_bichuv_"))
async def r_view_bichuv_detail(cb: types.CallbackQuery):
    kod = cb.data.replace("r_view_bichuv_", "")
    conn = sqlite3.connect("fabrika.db")
    res = conn.execute("SELECT model, razmer, soni FROM bichuv_ombor WHERE kod=? AND status=1", (kod,)).fetchall()
    conn.close()
    if not res: return await cb.answer("❌ Ma'lumot topilmadi.", show_alert=True)
    txt = f"📥 **Bichuvdan kelgan ish tafsilotlari (Kod: {kod}):**\n👗 Model: {res[0][0]}\n\n"
    jami = sum(r[2] for r in res)
    for r in res: txt += f"🔹 R: {r[1]} — {r[2]} ta\n"
    txt += f"\n💰 **Jami: {jami} ta**\n\nOmborga qabul qilasizmi?"
    ikb = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"r_acc_{kod}"), types.InlineKeyboardButton(text="❌ Rad etish", callback_data=f"r_rej_{kod}"))
    await cb.message.edit_text(txt, reply_markup=ikb.as_markup())

@dp.callback_query(F.data.startswith("r_acc_"))
async def r_acc_cb(cb: types.CallbackQuery):
    kod = cb.data.replace("r_acc_", "")
    conn = sqlite3.connect("fabrika.db")
    ishlar = conn.execute("SELECT model, kod, razmer, soni FROM bichuv_ombor WHERE kod=? AND status=1", (kod,)).fetchall()
    for ish in ishlar: conn.execute("INSERT INTO razdacha_ombor (model, kod, razmer, soni) VALUES (?,?,?,?)", ish)
    conn.execute("DELETE FROM bichuv_ombor WHERE kod=? AND status=1", (kod,))
    conn.commit()
    conn.close()
    await cb.message.edit_text(f"✅ Kod {kod} omborga qabul qilindi.")

@dp.callback_query(F.data.startswith("r_rej_"))
async def r_rej_cb(cb: types.CallbackQuery):
    kod = cb.data.replace("r_rej_", "")
    conn = sqlite3.connect("fabrika.db")
    conn.execute("UPDATE bichuv_ombor SET status=0 WHERE kod=?", (kod,))
    conn.commit()
    conn.close()
    await cb.message.edit_text(f"❌ Kod {kod} rad etildi va bichuvga qaytarildi.")

@dp.message(F.text == "✂️ Chevarga ish berish", StateFilter("*"))
async def raz_give_1(m: types.Message, state: FSMContext):
    await state.set_state(RazdachaState.target_ch)
    await m.answer("👤 Chevar kodi (Masalan: 101):", reply_markup=back_kb())

@dp.message(RazdachaState.target_ch)
async def raz_give_2(m: types.Message, state: FSMContext):
    if not m.text.isdigit(): return await m.answer("ID raqam kiring!")
    ch_id = int(m.text)
    conn = sqlite3.connect("fabrika.db")
    chevar = conn.execute("SELECT ism FROM hodimlar WHERE id=? AND rol='chevar'", (ch_id,)).fetchone()
    if not chevar:
        conn.close()
        return await m.answer(f"❌ {ch_id}-kodli chevar topilmadi!")
    await state.update_data(ch_id=ch_id, ch_ism=chevar[0])
    items = conn.execute("SELECT DISTINCT model, kod FROM razdacha_ombor WHERE soni > 0").fetchall()
    conn.close()
    if not items: return await m.answer("🫙 Ombor bo'sh!")
    kb = ReplyKeyboardBuilder()
    for i in items: kb.add(types.KeyboardButton(text=f"{i[0]} ({i[1]})"))
    kb.row(types.KeyboardButton(text="🏠 Asosiy sahifa"))
    await state.set_state(RazdachaState.model_tanlash)
    await m.answer(f"👤 Chevar: {chevar[0]}\n👗 Modelni tanlang:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(RazdachaState.model_tanlash)
async def raz_give_3(m: types.Message, state: FSMContext):
    try:
        parts = m.text.split(" (")
        mod, kod = parts[0], parts[1].replace(")", "")
        await state.update_data(mod=mod, kod=kod)
        conn = sqlite3.connect("fabrika.db")
        stock_items = conn.execute("SELECT razmer, soni FROM razdacha_ombor WHERE kod=? AND soni > 0", (kod,)).fetchall()
        conn.close()
        stock_txt = f"📦 **{mod} ({kod}) ombor qoldig'i:**\n\n"
        kb = ReplyKeyboardBuilder()
        for item in stock_items:
            stock_txt += f"• R:{item[0]} — {item[1]} ta\n"
            kb.add(types.KeyboardButton(text=str(item[0])))
        await m.answer(stock_txt, parse_mode="Markdown")
        kb.row(types.KeyboardButton(text="🏠 Asosiy sahifa")).adjust(3)
        await state.set_state(RazdachaState.razmer_tanlash)
        await m.answer("📏 Razmerni tanlang:", reply_markup=kb.as_markup(resize_keyboard=True))
    except Exception as e:
        logging.error(f"raz_give_3 xatosi: {e}")
        await m.answer("⚠️ Iltimos, modelni menudan tanlang!")

@dp.message(RazdachaState.razmer_tanlash)
async def raz_give_4(m: types.Message, state: FSMContext):
    await state.update_data(raz=m.text)
    await state.set_state(RazdachaState.soni)
    await m.answer("🔢 Soni:", reply_markup=back_kb())

@dp.message(RazdachaState.soni)
async def raz_give_5(m: types.Message, state: FSMContext):
    if not m.text.isdigit() or int(m.text) <= 0: return await m.answer("⚠️ Iltimos, 0 dan katta raqam kiriting!")
    soni = int(m.text)
    d = await state.get_data()
    conn = sqlite3.connect("fabrika.db")
    res = conn.execute("SELECT soni FROM razdacha_ombor WHERE kod=? AND razmer=?", (d['kod'], d['raz'])).fetchone()
    conn.close()
    stock = res[0] if res else 0
    if soni > stock: return await m.answer(f"❌ Omborda faqat {stock} ta bor!")
    await state.update_data(soni=soni)
    kb = ReplyKeyboardBuilder().row(types.KeyboardButton(text="✅ Ha"), types.KeyboardButton(text="❌ Yo'q"))
    confirm_text = f"⚠️ Ma'lumotni tasdiqlaysizmi?\n\n👤 Chevar: {d['ch_ism']}\n👗 Model: {d['mod']} ({d['kod']})\n📏 Razmer: {d['raz']}\n🔢 Soni: {soni} ta"
    await state.set_state(RazdachaState.tasdiqlash)
    await m.answer(confirm_text, reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(RazdachaState.tasdiqlash)
async def raz_give_final(m: types.Message, state: FSMContext):
    if m.text == "✅ Ha":
        d = await state.get_data()
        conn = sqlite3.connect("fabrika.db")
        biri = conn.execute("SELECT id FROM hodimlar WHERE chat_id=?", (m.from_user.id,)).fetchone()
        biri_id = biri[0] if biri else None
        conn.execute(
            "INSERT INTO ishlar (model, kod, razmer, umumiy_soni, qolgan_soni, chevar_id, status, vaqt, biriktirgan_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (d['mod'], d['kod'], d['raz'], d['soni'], d['soni'], d['ch_id'], 'kutilmoqda',
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"), biri_id)
        )
        conn.execute("UPDATE razdacha_ombor SET soni = soni - ? WHERE kod=? AND razmer=?", (d['soni'], d['kod'], d['raz']))
        conn.commit()
        conn.close()
        await m.answer(f"✅ {d['soni']} ta ish {d['ch_ism']}ga yuborildi!", reply_markup=get_main_menu('razdacha'))
        await state.clear()
    else:
        await m.answer("🚫 Amaliyot bekor qilindi.", reply_markup=get_main_menu('razdacha'))
        await state.clear()
# --- RAZDACHA MONITORING ---

@dp.message(F.text == "⏳ Kutilayotgan ishlar", StateFilter("*"))
async def raz_pending_works(m: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("fabrika.db")
    pending = conn.execute("SELECT i.id, h.ism, i.model, i.kod, i.razmer, i.umumiy_soni, i.vaqt FROM ishlar i JOIN hodimlar h ON i.chevar_id = h.id WHERE i.status = 'kutilmoqda'").fetchall()
    conn.close()
    if not pending: return await m.answer("✅ Kutilayotgan ish yo'q.")
    for p in pending:
        txt = f"👤 **{p[1]}**\n👗 {p[2]} ({p[3]}) | R:{p[4]} | **{p[5]} ta**\n🕒 {p[6]}"
        ikb = InlineKeyboardBuilder().row(types.InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"raz_cancel_{p[0]}"))
        await m.answer(txt, parse_mode="Markdown", reply_markup=ikb.as_markup())

@dp.callback_query(F.data.startswith("raz_cancel_"))
async def raz_cancel_pending_work(cb: types.CallbackQuery):
    ish_id = cb.data.replace("raz_cancel_", "")
    conn = sqlite3.connect("fabrika.db")
    ish = conn.execute("SELECT kod, razmer, umumiy_soni FROM ishlar WHERE id=?", (ish_id,)).fetchone()
    if ish:
        kod, razmer, soni = ish
        conn.execute("DELETE FROM ishlar WHERE id=?", (ish_id,))
        conn.execute("UPDATE razdacha_ombor SET soni = soni + ? WHERE kod=? AND razmer=?", (soni, kod, razmer))
        conn.commit()
        conn.close()
        await cb.message.edit_text(f"🚫 Ish bekor qilindi.\n✅ {soni} ta mahsulot omborga qaytarildi.")
    else:
        conn.close()
        await cb.answer("❌ Bu ish allaqachon bekor qilingan.", show_alert=True)

@dp.message(F.text == "🧵 Tikuvdagi topshiriqlar", StateFilter("*"))
async def raz_tikuv_menu(m: types.Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardBuilder()
    kb.row(
        types.InlineKeyboardButton(text="📋 Ro'yxat", callback_data="tikuv_royxat_0"),
        types.InlineKeyboardButton(text="🔄 Qaytarish so'rovlari", callback_data="tikuv_qaytarish"),
    )
    await m.answer("🧵 **Tikuvdagi topshiriqlar**\n\nKerakli bo'limni tanlang:", parse_mode="Markdown", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("tikuv_royxat_"))
async def tikuv_royxat_cb(cb: types.CallbackQuery):
    page = int(cb.data.replace("tikuv_royxat_", ""))
    per_page = 8
    conn = sqlite3.connect("fabrika.db")
    chevars = conn.execute("""
        SELECT i.chevar_id, h.ism, COUNT(i.id), SUM(i.qolgan_soni)
        FROM ishlar i JOIN hodimlar h ON i.chevar_id = h.id
        WHERE i.qolgan_soni > 0 AND i.status IN ('tikilmoqda','topshirildi_kutilmoqda')
        GROUP BY i.chevar_id
    """).fetchall()
    conn.close()
    if not chevars:
        return await cb.message.edit_text("📭 Hozircha chevarlarda ish yo'q.")
    total = len(chevars)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = chevars[page * per_page:(page + 1) * per_page]
    kb = InlineKeyboardBuilder()
    for ch in chunk:
        kb.row(types.InlineKeyboardButton(
            text=f"🧵 ID {ch[0]} | {ch[1]} | Topshiriq: {ch[2]} ta | Qolgan: {ch[3]} ta",
            callback_data=f"ch_detail_{ch[0]}"
        ))
    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton(text="◀ Oldingi", callback_data=f"tikuv_royxat_{page-1}"))
    if page < total_pages - 1:
        nav.append(types.InlineKeyboardButton(text="Keyingi ▶", callback_data=f"tikuv_royxat_{page+1}"))
    if nav:
        kb.row(*nav)
    txt = f"📋 **Ro'yxat**\nAktual ishi bor chevarlar\nSahifa: {page+1}/{total_pages} | Jami: {total} ta"
    await cb.message.edit_text(txt, parse_mode="Markdown", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("ch_detail_"))
async def ch_detail_cb(cb: types.CallbackQuery):
    ch_id = cb.data.replace("ch_detail_", "")
    conn = sqlite3.connect("fabrika.db")
    r = conn.execute("SELECT ism FROM hodimlar WHERE id=?", (ch_id,)).fetchone()
    if not r:
        conn.close()
        return await cb.answer("❌ Chevar topilmadi!", show_alert=True)
    ism = r[0]
    works = conn.execute(
        "SELECT id, model, razmer, qolgan_soni FROM ishlar WHERE chevar_id=? AND qolgan_soni > 0 AND status IN ('tikilmoqda','topshirildi_kutilmoqda')",
        (ch_id,)
    ).fetchall()
    conn.close()
    count = len(works)
    total_q = sum(w[3] for w in works)
    kb = InlineKeyboardBuilder()
    for w in works:
        kb.row(types.InlineKeyboardButton(
            text=f"🧵 {w[1]} | BR {w[0]} | {w[2]} R | {w[3]} ta",
            callback_data=f"topshiriq_karta_{w[0]}"
        ))
    kb.row(types.InlineKeyboardButton(text="◀ Orqaga", callback_data="tikuv_royxat_0"))
    txt = (f"🧵 **Chevar bo'yicha aktiv ishlar**\n\n"
           f"👤 Chevar: {ism}\n🆔 Login ID: {ch_id}\n"
           f"📌 Aktiv topshiriq: {count} ta\n🧵 Jami qolgan: {total_q} ta\n\n"
           f"Kerakli topshiriqni tanlang:")
    await cb.message.edit_text(txt, parse_mode="Markdown", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("topshiriq_karta_"))
async def topshiriq_karta_cb(cb: types.CallbackQuery):
    ish_id = int(cb.data.replace("topshiriq_karta_", ""))
    conn = sqlite3.connect("fabrika.db")
    ish = conn.execute(
        "SELECT model, kod, razmer, umumiy_soni, qolgan_soni, chevar_id, status, vaqt, biriktirgan_id, qabul_vaqt FROM ishlar WHERE id=?",
        (ish_id,)
    ).fetchone()
    if not ish:
        conn.close()
        return await cb.answer("❌ Topshiriq topilmadi!", show_alert=True)
    ch_r = conn.execute("SELECT ism FROM hodimlar WHERE id=?", (ish[5],)).fetchone()
    ch_ism = ch_r[0] if ch_r else f"ID:{ish[5]}"
    biri_ism = "—"
    if ish[8]:
        br = conn.execute("SELECT ism FROM hodimlar WHERE id=?", (ish[8],)).fetchone()
        if br:
            biri_ism = f"{br[0]} (ID:{ish[8]})"
    qaytgan = conn.execute(
        "SELECT COALESCE(SUM(miqdor),0) FROM qaytarish_sorovi WHERE ish_id=? AND holat='qabul'", (ish_id,)
    ).fetchone()[0]
    qs = conn.execute(
        "SELECT miqdor, sabab, vaqt FROM qaytarish_sorovi WHERE ish_id=? AND holat='ochiq' ORDER BY id DESC LIMIT 1",
        (ish_id,)
    ).fetchone()
    conn.close()
    holat_map = {
        'kutilmoqda':             '⏳ Razdacha tasdig\'ini kutmoqda',
        'tikilmoqda':             '🧵 Tikish jarayonida',
        'topshirildi_kutilmoqda': '📤 Topshirildi — qabul kutilmoqda',
        'yakunlandi':             '✅ Yakunlandi',
    }
    holat_txt = holat_map.get(ish[6], ish[6])
    qabul_txt = ish[9] if ish[9] else "—"
    txt = (f"📌 **Topshiriq kartasi**\n\n"
           f"👗 {ish[0]}  |  🔢 BR:{ish_id}  |  Kod:{ish[1]}  |  R:{ish[2]}\n"
           f"👤 Chevar: {ch_ism}\n"
           f"👤 Biriktirgan: {biri_ism}\n\n"
           f"📦 **Miqdorlar:**\n"
           f"   📦 Berilgan:       {ish[3]} ta\n"
           f"   ↩️ Qaytgan jami:   {qaytgan} ta\n"
           f"   🧵 Hali qolgan:    {ish[4]} ta\n\n"
           f"⚡ Holat: {holat_txt}\n"
           f"🕒 Biriktirilgan: {ish[7]}\n"
           f"✅ Qabul qilingan: {qabul_txt}")
    if qs:
        qoladi = ish[4] - qs[0]
        txt += (f"\n\n──────────────────────\n"
                f"⚠️ **Qaytarish so'rovi: OCHIQ**\n"
                f"   📦 Chevarda mavjud:      {ish[4]} ta\n"
                f"   ↩️ Qaytarish so'ralgan:  {qs[0]} ta\n"
                f"   📌 Qabul bo'lsa qoladi:  {qoladi} ta\n"
                f"   📝 Sabab: {qs[1]}\n"
                f"   🕒 So'rov vaqti: {qs[2]}")
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="◀ Orqaga", callback_data=f"ch_detail_{ish[5]}"))
    await cb.message.edit_text(txt, parse_mode="Markdown", reply_markup=kb.as_markup())

@dp.callback_query(F.data == "tikuv_qaytarish")
async def tikuv_qaytarish_cb(cb: types.CallbackQuery):
    conn = sqlite3.connect("fabrika.db")
    rows = conn.execute("""
        SELECT qs.id, h.ism, i.model, i.id, i.kod, i.razmer, qs.miqdor, i.qolgan_soni, qs.sabab, qs.vaqt
        FROM qaytarish_sorovi qs
        JOIN ishlar i ON qs.ish_id = i.id
        JOIN hodimlar h ON qs.chevar_id = h.id
        WHERE qs.holat='ochiq'
        ORDER BY qs.id DESC
    """).fetchall()
    conn.close()
    if not rows:
        return await cb.message.edit_text("✅ Ochiq qaytarish so'rovlari yo'q.")
    kb = InlineKeyboardBuilder()
    for r in rows:
        kb.row(types.InlineKeyboardButton(
            text=f"🔄 {r[1]} | {r[2]} | {r[6]} ta",
            callback_data=f"qs_detail_{r[0]}"
        ))
    kb.row(types.InlineKeyboardButton(text="◀ Orqaga", callback_data="tikuv_royxat_0"))
    txt = f"🔄 **Qaytarish so'rovlari**\n\nOchiq so'rovlar: {len(rows)} ta"
    await cb.message.edit_text(txt, parse_mode="Markdown", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("qs_detail_"))
async def qs_detail_cb(cb: types.CallbackQuery):
    qs_id = cb.data.replace("qs_detail_", "")
    conn = sqlite3.connect("fabrika.db")
    r = conn.execute("""
        SELECT qs.id, h.ism, qs.chevar_id, i.model, i.id, i.kod, i.razmer, qs.miqdor, i.qolgan_soni, qs.sabab, qs.vaqt
        FROM qaytarish_sorovi qs
        JOIN ishlar i ON qs.ish_id = i.id
        JOIN hodimlar h ON qs.chevar_id = h.id
        WHERE qs.id=?
    """, (qs_id,)).fetchone()
    conn.close()
    if not r:
        return await cb.answer("❌ So'rov topilmadi!", show_alert=True)
    qoladi = r[8] - r[7]
    txt = (f"🔄 **Qaytarish so'rovi**\n\n"
           f"👤 {r[1]} (ID:{r[2]})\n"
           f"👗 {r[3]} | BR:{r[4]} | Kod:{r[5]} | R:{r[6]}\n\n"
           f"📦 Chevarda mavjud:      {r[8]} ta\n"
           f"↩️ Qaytarish so'ralgan:  {r[7]} ta\n"
           f"📌 Qabul bo'lsa qoladi:  {qoladi} ta\n\n"
           f"📝 Sabab: {r[9]}\n"
           f"🕒 Vaqt: {r[10]}")
    kb = InlineKeyboardBuilder()
    kb.row(
        types.InlineKeyboardButton(text="✅ Qabul", callback_data=f"qs_qabul_{qs_id}"),
        types.InlineKeyboardButton(text="❌ Rad", callback_data=f"qs_rad_{qs_id}"),
    )
    kb.row(types.InlineKeyboardButton(text="◀ Orqaga", callback_data="tikuv_qaytarish"))
    await cb.message.edit_text(txt, parse_mode="Markdown", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("qs_qabul_"))
async def qs_qabul_cb(cb: types.CallbackQuery):
    qs_id = int(cb.data.replace("qs_qabul_", ""))
    conn = sqlite3.connect("fabrika.db")
    qs = conn.execute("SELECT ish_id, miqdor FROM qaytarish_sorovi WHERE id=? AND holat='ochiq'", (qs_id,)).fetchone()
    if not qs:
        conn.close()
        return await cb.answer("❌ So'rov topilmadi yoki allaqachon ko'rib chiqilgan!", show_alert=True)
    ish_id, miqdor = qs
    ish = conn.execute("SELECT qolgan_soni, kod, razmer FROM ishlar WHERE id=?", (ish_id,)).fetchone()
    new_q = ish[0] - miqdor
    new_status = 'yakunlandi' if new_q <= 0 else 'tikilmoqda'
    conn.execute("UPDATE ishlar SET qolgan_soni=?, status=? WHERE id=?", (max(0, new_q), new_status, ish_id))
    conn.execute("UPDATE razdacha_ombor SET soni = soni + ? WHERE kod=? AND razmer=?", (miqdor, ish[1], ish[2]))
    conn.execute("UPDATE qaytarish_sorovi SET holat='qabul' WHERE id=?", (qs_id,))
    conn.commit()
    conn.close()
    await cb.message.edit_text(f"✅ Qaytarish qabul qilindi. {miqdor} ta omborga qaytarildi.")

@dp.callback_query(F.data.startswith("qs_rad_"))
async def qs_rad_cb(cb: types.CallbackQuery):
    qs_id = cb.data.replace("qs_rad_", "")
    conn = sqlite3.connect("fabrika.db")
    conn.execute("UPDATE qaytarish_sorovi SET holat='rad' WHERE id=?", (qs_id,))
    conn.commit()
    conn.close()
    await cb.message.edit_text("❌ Qaytarish so'rovi rad etildi.")

# ================= CHEVAR BO'LIMI (TO'LIQ TUZATILGAN) =================

@dp.message(F.text == "📥 Qabul uchun ishlar", StateFilter("*"))
async def ch_inbound(m: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("fabrika.db")
    # Chat_id orqali chevarni aniqlash
    user = conn.execute("SELECT id FROM hodimlar WHERE chat_id=?", (m.from_user.id,)).fetchone()
    if not user:
        conn.close()
        return await m.answer("❌ Profil topilmadi. Qaytadan /start bosing.")
    
    my_id = user[0]
    # Faqat statusi 'kutilmoqda' va miqdori 0 dan katta ishlarni chiqarish
    ishlar = conn.execute("""
        SELECT id, model, kod, razmer, umumiy_soni 
        FROM ishlar 
        WHERE chevar_id=? AND status='kutilmoqda' AND umumiy_soni > 0
    """, (my_id,)).fetchall()
    conn.close()
    
    if not ishlar: 
        return await m.answer("📭 Hozircha yangi ishlar yo'q.")
    
    for i in ishlar:
        ikb = InlineKeyboardBuilder().row(
            types.InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"ch_accept_work_{i[0]}"), 
            types.InlineKeyboardButton(text="❌ Rad etish", callback_data=f"ch_rej_{i[0]}")
        )
        await m.answer(
            f"📦 **Yangi ish keldi:**\n\n👗 Model: {i[1]} ({i[2]})\n📏 Razmer: {i[3]}\n🔢 Soni: {i[4]} ta", 
            reply_markup=ikb.as_markup(), 
            parse_mode="Markdown"
        )

@dp.message(F.text == "🧵 Tikilayotgan ishlar", StateFilter("*"))
async def show_active_works(m: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("fabrika.db")
    user = conn.execute("SELECT id FROM hodimlar WHERE chat_id=?", (m.from_user.id,)).fetchone()
    if not user:
        conn.close()
        return await m.answer("❌ Profil topilmadi.")
    
    my_id = user[0]
    # MUHIM: Faqat qolgan_soni 0 dan katta ishlarni ko'rsatish
    works = conn.execute("""
        SELECT model, kod, razmer, qolgan_soni, status, topshirildi_soni 
        FROM ishlar 
        WHERE chevar_id=? 
        AND qolgan_soni > 0 
        AND status IN ('tikilmoqda', 'topshirildi_kutilmoqda') 
        ORDER BY status DESC
    """, (my_id,)).fetchall()
    conn.close()
    
    if not works: 
        return await m.answer("📭 Sizda hozircha faol ishlar yo'q.")
    
    txt = "🧵 **Sizdagi ishlar holati:**\n\n"
    for w in works:
        if w[4] == 'topshirildi_kutilmoqda':
            txt += f"📤 {w[0]} | R:{w[2]} | **{w[5]} ta topshirildi** — razdacha tasdig'ini kutmoqda\n"
        else:
            txt += f"🧵 {w[0]} | R:{w[2]} | **{w[3]} ta** — tikish jarayonida\n"
        txt += "------------------------\n"
    await m.answer(txt, parse_mode="Markdown")

@dp.message(F.text == "📤 Ish topshirish", StateFilter("*"))
async def ch_top_1(m: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("fabrika.db")
    user = conn.execute("SELECT id FROM hodimlar WHERE chat_id=?", (m.from_user.id,)).fetchone()
    if not user:
        conn.close()
        return await m.answer("❌ Profil topilmadi.")
    
    my_id = user[0]
    # Faqat tikilayotgan va soni 0 dan katta ishlarni topshirish mumkin
    ishlar = conn.execute("""
        SELECT id, model, kod, razmer, qolgan_soni 
        FROM ishlar 
        WHERE chevar_id=? AND status='tikilmoqda' AND qolgan_soni > 0
    """, (my_id,)).fetchall()
    conn.close()
    
    if not ishlar: 
        return await m.answer("📭 Topshirishga ish yo'q.")
    
    kb = ReplyKeyboardBuilder()
    for i in ishlar: 
        kb.add(types.KeyboardButton(text=f"ID:{i[0]} | {i[1]} R:{i[3]}"))
    kb.row(types.KeyboardButton(text="🏠 Asosiy sahifa")).adjust(1)
    
    await state.set_state(ChevarState.ish_tanlash)
    await m.answer("❓ Qaysi modelni topshirasiz?", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(ChevarState.ish_tanlash)
async def ch_top_2(m: types.Message, state: FSMContext):
    if m.text == "🏠 Asosiy sahifa":
        await state.clear()
        return await back_to_main(m, state)
    if "ID:" not in m.text: 
        return await m.answer("⚠️ Iltimos, menudan tanlang!")
    
    try:
        ish_id = m.text.split("|")[0].replace("ID:","").strip()
        await state.update_data(t_id=ish_id)
        await state.set_state(ChevarState.topshirish_soni)
        await m.answer("🔢 Necha dona topshirasiz?", reply_markup=back_kb())
    except: 
        await m.answer("❌ Ma'lumotda xatolik. Qaytadan urinib ko'ring.")

@dp.message(ChevarState.topshirish_soni)
async def ch_top_3(m: types.Message, state: FSMContext):
    if m.text == "🏠 Asosiy sahifa":
        await state.clear()
        return await back_to_main(m, state)
    if not m.text.isdigit(): 
        return await m.answer("⚠️ Faqat raqam kiriting!")
    
    soni, data = int(m.text), await state.get_data()
    t_id = data.get('t_id')
    
    conn = sqlite3.connect("fabrika.db")
    ish = conn.execute("SELECT qolgan_soni FROM ishlar WHERE id=?", (t_id,)).fetchone()
    
    if not ish or soni > ish[0] or soni <= 0:
        conn.close()
        return await m.answer(f"❌ Xato! Miqdor noto'g'ri (Max: {ish[0] if ish else 0}).")
    
    # Ishni topshirish statusiga o'tkazish
    conn.execute("UPDATE ishlar SET topshirildi_soni = ?, status = 'topshirildi_kutilmoqda' WHERE id=?", (soni, t_id))
    conn.commit()
    conn.close()
    
    await m.answer(f"✅ {soni} ta ish yuborildi. Razdacha qabulini kuting.", reply_markup=get_main_menu('chevar'))
    await state.clear()

# --- CALLBACKLAR (CHEVAR) ---

@dp.callback_query(F.data.startswith("ch_accept_work_"))
async def process_ch_accept(cb: types.CallbackQuery):
    ish_id = cb.data.replace("ch_accept_work_", "")
    conn = sqlite3.connect("fabrika.db")
    conn.execute(
        "UPDATE ishlar SET status='tikilmoqda', qabul_vaqt=? WHERE id=?",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ish_id)
    )
    conn.commit()
    conn.close()
    await cb.answer("Ish qabul qilindi!")
    await cb.message.edit_text("✅ Ish qabul qilindi. Tikishni boshlashingiz mumkin!")

@dp.callback_query(F.data.startswith("ch_rej_"))
async def process_ch_reject(cb: types.CallbackQuery):
    ish_id = cb.data.replace("ch_rej_", "")
    conn = sqlite3.connect("fabrika.db")
    ish = conn.execute("SELECT kod, razmer, umumiy_soni FROM ishlar WHERE id=?", (ish_id,)).fetchone()
    if ish:
        conn.execute("DELETE FROM ishlar WHERE id=?", (ish_id,))
        # Omborga qaytarishda kod va razmerni tekshirib qaytarish
        conn.execute("UPDATE razdacha_ombor SET soni = soni + ? WHERE kod=? AND razmer=?", (ish[2], ish[0], ish[1]))
        conn.commit()
        await cb.message.edit_text("🚫 Ish rad etildi va omborga qaytarildi.")
    conn.close()

# ================= RAZDACHA BO'LIMI =================

@dp.message(F.text == "🏁 Chevardan ish olish", StateFilter("*"))
async def raz_from_ch_list(m: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("fabrika.db")
    chevarlar = conn.execute("""
        SELECT DISTINCT i.chevar_id, h.ism 
        FROM ishlar i 
        JOIN hodimlar h ON i.chevar_id = h.id 
        WHERE i.status='topshirildi_kutilmoqda'
    """).fetchall()
    conn.close()
    
    if not chevarlar: 
        return await m.answer("📭 Topshirilgan ishlar yo'q.")
    
    kb = InlineKeyboardBuilder()
    for ch in chevarlar: 
        kb.row(types.InlineKeyboardButton(text=f"👤 {ch[1]}", callback_data=f"raz_view_ch_{ch[0]}"))
    await m.answer("🏁 Ish topshirgan chevarlar:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("raz_view_ch_"))
async def raz_view_ch_items(cb: types.CallbackQuery):
    ch_id = cb.data.replace("raz_view_ch_", "")
    conn = sqlite3.connect("fabrika.db")
    ishlar = conn.execute("SELECT id, model, kod, razmer, topshirildi_soni FROM ishlar WHERE chevar_id=? AND status='topshirildi_kutilmoqda'", (ch_id,)).fetchall()
    conn.close()
    for i in ishlar:
        ikb = InlineKeyboardBuilder().row(
            types.InlineKeyboardButton(text="✅ Qabul", callback_data=f"raz_v_acc_{i[0]}"), 
            types.InlineKeyboardButton(text="❌ Rad", callback_data=f"raz_v_rej_{i[0]}")
        )
        await cb.message.answer(f"🔹 {i[1]} ({i[2]}) | R:{i[3]} | {i[4]} ta", reply_markup=ikb.as_markup())

@dp.callback_query(F.data.startswith("raz_v_acc_"))
async def raz_v_acc_cb(cb: types.CallbackQuery):
    ish_id = cb.data.replace("raz_v_acc_", "")
    conn = sqlite3.connect("fabrika.db")
    ish = conn.execute("SELECT topshirildi_soni, qolgan_soni, chevar_id, model, kod, razmer FROM ishlar WHERE id=?", (ish_id,)).fetchone()
    
    if not ish: 
        conn.close()
        return await cb.message.edit_text("❌ Xatolik.")
    
    yuborilgan = ish[0]
    qolgan = ish[1]
    new_qolgan = qolgan - yuborilgan
    
    # Agar hamma ish topshirilgan bo'lsa 'yakunlandi', aks holda yana 'tikilmoqda'
    status = 'tikilmoqda' if new_qolgan > 0 else 'yakunlandi'
    
    conn.execute("UPDATE ishlar SET qolgan_soni = ?, topshirildi_soni = 0, status = ? WHERE id=?", (new_qolgan, status, ish_id))
    
    # Tarixga qo'shish
    hozir = datetime.now()
    conn.execute("""
        INSERT INTO bitgan_ishlar (vaqt, chevar_id, model_nomi, kodi, razmer, soni, holat, sana) 
        VALUES (?,?,?,?,?,?,?,?)
    """, (hozir.strftime("%H:%M"), ish[2], ish[3], ish[4], ish[5], yuborilgan, "qabul qilindi", hozir.strftime("%d.%m")))
    
    conn.commit()
    conn.close()
    await cb.message.edit_text(f"✅ {yuborilgan} ta qabul qilindi. (Qoldi: {new_qolgan} ta)")

@dp.callback_query(F.data.startswith("raz_v_rej_"))
async def raz_v_rej_cb(cb: types.CallbackQuery):
    ish_id = cb.data.replace("raz_v_rej_", "")
    conn = sqlite3.connect("fabrika.db")
    conn.execute("UPDATE ishlar SET status = 'tikilmoqda', topshirildi_soni = 0 WHERE id = ?", (ish_id,))
    conn.commit()
    conn.close()
    await cb.message.edit_text("❌ Ish rad etildi va chevarga qaytarildi.")

# ================= ASOSIY VA STATISTIKA =================

@dp.message(F.text == "📦 Ombor holati", StateFilter("*"))
async def raz_ombor_status(m: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("fabrika.db")
    items = conn.execute("SELECT model, kod, razmer, soni FROM razdacha_ombor WHERE soni > 0 ORDER BY model ASC").fetchall()
    conn.close()
    if not items: 
        return await m.answer("📭 Ombor bo'sh.")
    
    txt, curr = "📦 **Razdacha ombori:**\n", ""
    for i in items:
        if curr != i[0]:
            txt += f"\n👗 **{i[0]} ({i[1]}):**\n"
            curr = i[0]
        txt += f"   • R:{i[2]} — {i[3]} ta\n"
    await m.answer(txt, parse_mode="Markdown")

@dp.message(F.text == "📊 Kunlik malumotlar", StateFilter("*"))
async def admin_stats(m: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("fabrika.db")
    user = conn.execute("SELECT rol FROM hodimlar WHERE chat_id=?", (m.from_user.id,)).fetchone()
    if not user or user[0] != 'admin':
        conn.close()
        return await m.answer("⛔️ Faqat adminlar uchun!")
    bugun = datetime.now().strftime("%d.%m")
    tikilgan = conn.execute("SELECT SUM(soni) FROM bitgan_ishlar WHERE sana=?", (bugun,)).fetchone()[0] or 0
    razdacha = conn.execute("SELECT SUM(soni) FROM razdacha_ombor").fetchone()[0] or 0
    bichuv = conn.execute("SELECT SUM(soni) FROM bichuv_ombor WHERE status=0").fetchone()[0] or 0
    conn.close()
    await m.answer(
        f"📊 **Bugungi ({bugun}) hisobot:**\n\n"
        f"✅ Bugun razdacha qabul qildi: {tikilgan} ta\n"
        f"📦 Razdacha omborida (jami): {razdacha} ta\n"
        f"✂️ Bichuvdan kelmagan (jami): {bichuv} ta",
        parse_mode="Markdown"
    )

# --- ADMIN: NARX BELGILASH HANDLERLARI ---
@dp.message(F.text == "💰 Narx belgilash", StateFilter("*"))
async def admin_narx_start(m: types.Message, state: FSMContext):
    conn = sqlite3.connect("fabrika.db")
    user = conn.execute("SELECT rol FROM hodimlar WHERE chat_id=?", (m.from_user.id,)).fetchone()
    conn.close()
    if not user or user[0] != 'admin':
        return await m.answer("⛔️ Faqat adminlar uchun!")
    await state.set_state(NarxState.bichuv_id)
    await m.answer("🔢 Narx belgilash uchun **Bichuv kodini** kiriting (masalan: 101):", parse_mode="Markdown")

@dp.message(NarxState.bichuv_id)
async def admin_narx_id(m: types.Message, state: FSMContext):
    conn = sqlite3.connect("fabrika.db")
    res = conn.execute("SELECT DISTINCT model FROM bichuv_ombor WHERE kod=?", (m.text,)).fetchone()
    conn.close()
    if not res:
        return await m.answer(f"❌ '{m.text}' kodli bichuv topilmadi.")
    await state.update_data(b_id=m.text, m_nomi=res[0])
    await state.set_state(NarxState.summa)
    await m.answer(f"📦 Model: **{res[0]}**\n💰 1 dona uchun narxni kiriting:", parse_mode="Markdown")

@dp.message(NarxState.summa)
async def admin_narx_final(m: types.Message, state: FSMContext):
    if not m.text.isdigit():
        return await m.answer("⚠️ Faqat raqam kiriting!")
    data = await state.get_data()
    conn = sqlite3.connect("fabrika.db")
    conn.execute("INSERT OR REPLACE INTO tariflar (bichuv_id, narx) VALUES (?, ?)", (data['b_id'], int(m.text)))
    conn.commit()
    conn.close()
    await m.answer(f"✅ Saqlandi! {data['b_id']} = {m.text} so'm")
    await state.clear()

# --- CHEVAR: BALANS ---
@dp.message(F.text == "💰 Mening balansim", StateFilter("*"))
async def chevar_balans_hisob(m: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("fabrika.db")
    user = conn.execute("SELECT id, ism FROM hodimlar WHERE chat_id=?", (m.from_user.id,)).fetchone()
    if not user: return await m.answer("❌ Profil topilmadi.")
    
    query = """
    SELECT b.model_nomi, b.kodi, SUM(b.soni), IFNULL(t.narx, 0)
    FROM bitgan_ishlar b
    LEFT JOIN tariflar t ON b.kodi = t.bichuv_id
    WHERE b.chevar_id = ? GROUP BY b.kodi
    """
    rows = conn.execute(query, (user[0],)).fetchall()
    conn.close()
    if not rows: return await m.answer("📭 Bitgan ishlar yo'q.")
    
    txt = f"👤 {user[1]}\n\n📋 Modellar bo'yicha:\n"
    total = 0
    for r in rows:
        summa = r[2] * r[3]
        total += summa
        if r[3] > 0:
            txt += f"• {r[0]} ({r[1]}): {r[2]} ta × {r[3]:,} so'm = {summa:,} so'm\n"
        else:
            txt += f"• {r[0]} ({r[1]}): {r[2]} ta × narx belgilanmagan\n"
    txt += f"\n💰 Jami balans: {total:,} so'm"
    await m.answer(txt)

# --- CHEVAR: ISH QAYTARISH ---
@dp.message(F.text == "↩️ Ish qaytarish", StateFilter("*"))
async def ch_qaytarish_1(m: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("fabrika.db")
    user = conn.execute("SELECT id FROM hodimlar WHERE chat_id=?", (m.from_user.id,)).fetchone()
    if not user:
        conn.close()
        return await m.answer("❌ Profil topilmadi.")
    ishlar = conn.execute(
        "SELECT id, model, razmer, qolgan_soni FROM ishlar WHERE chevar_id=? AND status='tikilmoqda' AND qolgan_soni > 0",
        (user[0],)
    ).fetchall()
    conn.close()
    if not ishlar:
        return await m.answer("📭 Qaytarish uchun faol ish yo'q.")
    kb = ReplyKeyboardBuilder()
    for i in ishlar:
        kb.add(types.KeyboardButton(text=f"ID:{i[0]} | {i[1]} R:{i[2]}"))
    kb.row(types.KeyboardButton(text="🏠 Asosiy sahifa")).adjust(1)
    await state.set_state(ChevarQaytarishState.ish_tanlash)
    await m.answer("↩️ Qaytarish uchun ish tanlang:", reply_markup=kb.as_markup(resize_keyboard=True))

@dp.message(ChevarQaytarishState.ish_tanlash)
async def ch_qaytarish_2(m: types.Message, state: FSMContext):
    if m.text == "🏠 Asosiy sahifa":
        await state.clear()
        return await back_to_main(m, state)
    if "ID:" not in m.text:
        return await m.answer("⚠️ Iltimos, menudan tanlang!")
    try:
        ish_id = int(m.text.split("|")[0].replace("ID:", "").strip())
    except (ValueError, IndexError):
        return await m.answer("❌ Xatolik. Qaytadan urinib ko'ring.")
    conn = sqlite3.connect("fabrika.db")
    ish = conn.execute("SELECT qolgan_soni, model, kod, razmer FROM ishlar WHERE id=?", (ish_id,)).fetchone()
    conn.close()
    if not ish:
        return await m.answer("❌ Ish topilmadi.")
    await state.update_data(ish_id=ish_id, qolgan_soni=ish[0], model=ish[1], kod=ish[2], razmer=ish[3])
    await state.set_state(ChevarQaytarishState.miqdor)
    await m.answer(f"🔢 Necha tani qaytarmoqchisiz?\n(Maksimal: {ish[0]} ta)", reply_markup=back_kb())

@dp.message(ChevarQaytarishState.miqdor)
async def ch_qaytarish_3(m: types.Message, state: FSMContext):
    if m.text == "🏠 Asosiy sahifa":
        await state.clear()
        return await back_to_main(m, state)
    if not m.text.isdigit() or int(m.text) <= 0:
        return await m.answer("⚠️ Faqat musbat raqam kiriting!")
    data = await state.get_data()
    miqdor = int(m.text)
    if miqdor > data['qolgan_soni']:
        return await m.answer(f"❌ Maksimal {data['qolgan_soni']} ta qaytarish mumkin!")
    await state.update_data(miqdor=miqdor)
    await state.set_state(ChevarQaytarishState.sabab)
    await m.answer("📝 Qaytarish sababini yozing (sabab yo'q bo'lsa — yozing):", reply_markup=back_kb())

@dp.message(ChevarQaytarishState.sabab)
async def ch_qaytarish_4(m: types.Message, state: FSMContext):
    if m.text == "🏠 Asosiy sahifa":
        await state.clear()
        return await back_to_main(m, state)
    data = await state.get_data()
    vaqt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect("fabrika.db")
    user = conn.execute("SELECT id FROM hodimlar WHERE chat_id=?", (m.from_user.id,)).fetchone()
    chevar_id = user[0] if user else None
    conn.execute(
        "INSERT INTO qaytarish_sorovi (ish_id, chevar_id, miqdor, sabab, vaqt) VALUES (?,?,?,?,?)",
        (data['ish_id'], chevar_id, data['miqdor'], m.text, vaqt)
    )
    conn.commit()
    # Razdachaga xabar yuborish
    razdacha = conn.execute("SELECT chat_id, ism FROM hodimlar WHERE rol='razdacha' AND chat_id IS NOT NULL").fetchone()
    ch_ism = conn.execute("SELECT ism FROM hodimlar WHERE id=?", (chevar_id,)).fetchone()
    conn.close()
    if razdacha and razdacha[0]:
        qoladi = data['qolgan_soni'] - data['miqdor']
        notif = (
            f"🔄 **Qaytarish so'rovi keldi!**\n\n"
            f"👤 {ch_ism[0] if ch_ism else chevar_id} (ID:{chevar_id})\n"
            f"👗 {data['model']} | BR:{data['ish_id']} | Kod:{data['kod']} | R:{data['razmer']}\n\n"
            f"📦 Chevarda mavjud:      {data['qolgan_soni']} ta\n"
            f"↩️ Qaytarish so'ralgan:  {data['miqdor']} ta\n"
            f"📌 Qabul bo'lsa qoladi:  {qoladi} ta\n\n"
            f"📝 Sabab: {m.text}\n"
            f"🕒 Vaqt: {vaqt}"
        )
        try:
            await bot.send_message(razdacha[0], notif, parse_mode="Markdown")
        except Exception:
            pass
    await m.answer("✅ Qaytarish so'rovingiz yuborildi. Razdacha ko'rib chiqadi.", reply_markup=get_main_menu('chevar'))
    await state.clear()

# --- RAZDACHA: BITGAN ISHLAR TARIXI ---
@dp.message(F.text == "📜 Bitgan ishlar tarixi", StateFilter("*"))
async def raz_tarix(m: types.Message, state: FSMContext):
    await state.clear()
    conn = sqlite3.connect("fabrika.db")
    rows = conn.execute("""
        SELECT b.sana, h.ism, b.model_nomi, b.kodi, b.razmer, b.soni
        FROM bitgan_ishlar b
        JOIN hodimlar h ON b.chevar_id = h.id
        ORDER BY b.sana DESC, b.id DESC
        LIMIT 50
    """).fetchall()
    conn.close()
    if not rows:
        return await m.answer("📭 Tarix bo'sh.")
    txt = "📜 **Bitgan ishlar tarixi (so'nggi 50):**\n"
    curr_sana = ""
    for r in rows:
        if r[0] != curr_sana:
            txt += f"\n📅 **{r[0]}**\n"
            curr_sana = r[0]
        txt += f"  👤 {r[1]} | {r[2]} ({r[3]}) R:{r[4]} — {r[5]} ta\n"
    await m.answer(txt, parse_mode="Markdown")

# --- ASOSIY ISHGA TUSHIRISH FUNKSIYASI (Yagona va To'g'ri variant) ---
async def main():
    # 1. Jadvallarni yaratish/tekshirish
    init_db()

    # 3. Backup tizimi
    if not os.path.exists("backups"): 
        os.makedirs("backups")
    if os.path.exists("fabrika.db"): 
        try:
            shutil.copyfile("fabrika.db", f"backups/backup_{datetime.now().strftime('%d_%m_%H_%M')}.db")
            print("📁 Baza backup qilindi.")
        except Exception as e:
            print(f"⚠️ Backupda xatolik: {e}")
    
    # 4. Botni yurgizish
    print("🚀 Bot ishga tushdi...")
    await dp.start_polling(bot)

# FAQAT BITTA MANA SHU BLOK QOLSIN
if __name__ == "__main__":
    try: 
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit): 
        print("Bot to'xtatildi.")
