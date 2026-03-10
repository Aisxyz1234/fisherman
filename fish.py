"""
Fisherman Safety Monitoring System  v3.0
=========================================
Features:
  - Fisherman Registry (add / search)
  - Coast Guard Alert Panel with real-time IP-based location detection
  - Twilio Voice Call Alert  → fisherman's phone RINGS with spoken SOS message
  - Twilio SMS Alert         → fisherman receives GPS coordinates via SMS
  - Demo mode when no credentials configured
  - Full alert log with preview + CSV export
  - Settings tab to configure Twilio credentials at runtime

Setup:
  1. pip install twilio requests
  2. Sign up free at https://twilio.com (no credit card needed)
  3. From Twilio Console copy:
       Account SID  →  starts with "AC..."
       Auth Token   →  32-character string
       Phone Number →  your Twilio number e.g. +12345678900
  4. Paste them in the ⚙️ Settings tab inside the app
  5. Verify each fisherman's number in Twilio Console (free trial requirement)
       Twilio Console → Phone Numbers → Verified Caller IDs → Add New

Run:
  python fisherman_safety_system.py
"""

import tkinter as tk
from tkinter import ttk, messagebox
import math, csv, os, random, threading
from datetime import datetime

# ── Optional dependencies ─────────────────────────────────────────────────
try:
    import requests
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False

try:
    from twilio.rest import Client as TwilioClient
    TWILIO_OK = True
except ImportError:
    TWILIO_OK = False

# ── Twilio credentials (set via Settings tab or environment variables) ─────
TWILIO_SID   = os.environ.get("TWILIO_SID",   "")
TWILIO_TOKEN = os.environ.get("TWILIO_TOKEN",  "")
TWILIO_FROM  = os.environ.get("TWILIO_FROM",   "")  # e.g. +12015551234

# ── Sample fishermen dataset ───────────────────────────────────────────────
SAMPLE_FISHERMEN = [
    {"id":"FSH001","name":"Rajan Kumar",   "phone":"+919876543210","boat_id":"KL-01-F-1001","home_port":"Kochi",             "lat":9.9312, "lon":76.2673},
    {"id":"FSH002","name":"Murugan S",     "phone":"+919876543211","boat_id":"KL-02-F-2034","home_port":"Alappuzha",         "lat":9.4981, "lon":76.3388},
    {"id":"FSH003","name":"Sathish P",     "phone":"+919876543212","boat_id":"KL-04-F-3021","home_port":"Kollam",            "lat":8.8932, "lon":76.6141},
    {"id":"FSH004","name":"Biju Thomas",   "phone":"+919876543213","boat_id":"KL-06-F-4412","home_port":"Thrissur",          "lat":10.5276,"lon":76.2144},
    {"id":"FSH005","name":"Anwar Hussain", "phone":"+919876543214","boat_id":"KL-07-F-5561","home_port":"Kozhikode",         "lat":11.2588,"lon":75.7804},
    {"id":"FSH006","name":"Pradeep Nair",  "phone":"+919876543215","boat_id":"KL-09-F-6002","home_port":"Kannur",            "lat":11.8745,"lon":75.3704},
    {"id":"FSH007","name":"Suresh Pillai", "phone":"+919876543216","boat_id":"KL-11-F-7234","home_port":"Thiruvananthapuram","lat":8.5241, "lon":76.9366},
    {"id":"FSH008","name":"Dasan V",       "phone":"+919876543217","boat_id":"KL-12-F-8801","home_port":"Malappuram",        "lat":10.7867,"lon":76.0740},
    {"id":"FSH009","name":"Krishnan M",    "phone":"+919876543218","boat_id":"KL-03-F-9103","home_port":"Ernakulam",         "lat":10.1632,"lon":76.2402},
    {"id":"FSH010","name":"Joseph Antony", "phone":"+919876543219","boat_id":"KL-05-F-0234","home_port":"Kasaragod",         "lat":12.4996,"lon":74.9869},
]

# ══════════════════════════════════════════════════════════════════════════
#  HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2-lat1); dl = math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def generate_id():
    return f"FSH{random.randint(100,999)}"

def build_sms_text(name, dist_km, lat, lon):
    """SMS with GPS coordinates and Google Maps navigation link."""
    maps_link = f"https://maps.google.com/?q={lat:.5f},{lon:.5f}"
    return (
        f"SOS EMERGENCY ALERT\n"
        f"A fisherman is in DANGER!\n"
        f"\n"
        f"Distress Location:\n"
        f"Lat: {lat:.5f}  Lon: {lon:.5f}\n"
        f"\n"
        f"Tap to Navigate:\n"
        f"{maps_link}\n"
        f"\n"
        f"Dear {name}, you are {dist_km:.1f} km away.\n"
        f"Go to their location immediately!\n"
        f"Coast Guard: 112\n"
        f"-FishermanSafetySystem"
    )

def build_voice_twiml(name, dist_km, lat, lon):
    """TwiML spoken aloud when fisherman picks up the call."""
    msg = (
        f"Warning! Warning! Warning! "
        f"This is an emergency alert from the Fisherman Safety Monitoring System. "
        f"A fisherman is in danger near latitude {lat:.2f} and longitude {lon:.2f}. "
        f"Dear {name}, you are approximately {dist_km:.0f} kilometres away. "
        f"Please go to their location immediately or call Coast Guard on 1 1 2. "
        f"An SMS with the exact location and a Google Maps link has been sent to you. "
        f"Please check your messages immediately. "
        f"I repeat. A fisherman is in danger. You are {dist_km:.0f} kilometres away. "
        f"Check your SMS for the Google Maps link. Call Coast Guard on 1 1 2. "
    )
    return (
        f'<Response>'
        f'<Say voice="alice" language="en-IN" loop="3">{msg}</Say>'
        f'<Pause length="1"/>'
        f'</Response>'
    )

def twilio_call(sid, token, from_num, to_num, twiml):
    """
    Make a real voice call via Twilio.
    Returns (success: bool, message: str)
    """
    if not TWILIO_OK:
        return False, "twilio library not installed. Run: pip install twilio"
    try:
        client = TwilioClient(sid, token)
        call = client.calls.create(
            to=to_num,
            from_=from_num,
            twiml=twiml
        )
        return True, f"Call SID: {call.sid}"
    except Exception as e:
        return False, str(e)

def twilio_sms(sid, token, from_num, to_num, message):
    """
    Send a real SMS via Twilio.
    Returns (success: bool, message: str)
    """
    if not TWILIO_OK:
        return False, "twilio library not installed. Run: pip install twilio"
    try:
        client = TwilioClient(sid, token)
        msg = client.messages.create(
            to=to_num,
            from_=from_num,
            body=message
        )
        return True, f"SMS SID: {msg.sid}"
    except Exception as e:
        return False, str(e)

def get_location_by_ip():
    """
    Fetch real-time GPS coordinates via IP geolocation (ipinfo.io).
    Free, no API key needed.
    Returns (lat, lon, city_string)
    """
    if not REQUESTS_OK:
        raise RuntimeError("'requests' not installed. Run: pip install requests")
    r = requests.get("https://ipinfo.io/json", timeout=8)
    r.raise_for_status()
    d = r.json()
    loc = d.get("loc", "")
    if not loc:
        raise ValueError("No location returned by geolocation service.")
    lat, lon = map(float, loc.split(","))
    city = f"{d.get('city','?')}, {d.get('region','')}"
    return lat, lon, city


# ══════════════════════════════════════════════════════════════════════════
#  MAIN APPLICATION
# ══════════════════════════════════════════════════════════════════════════

class App(tk.Tk):
    # ── Colour palette ────────────────────────────────────────────────────
    BG     = "#0A1628"   # deep navy background
    PANEL  = "#0F2040"   # side panel / section bg
    CARD   = "#132847"   # input fields / cards
    ACCENT = "#00C6FF"   # cyan highlight
    RED    = "#FF4E50"   # danger / SOS red
    GREEN  = "#00E676"   # success green
    WARN   = "#FFB300"   # warning amber
    TEXT   = "#E8F4FD"   # primary text
    SUB    = "#7EB8D4"   # secondary / label text
    BORDER = "#1E3A5F"   # subtle border
    HDR    = "#0D1F38"   # header bar

    def __init__(self):
        super().__init__()
        self.title("Fisherman Safety Monitoring System  v3.0")
        self.geometry("1340x860")
        self.minsize(1100, 720)
        self.configure(bg=self.BG)

        # data
        self.fishermen = list(SAMPLE_FISHERMEN)
        self.alert_log = []

        # Twilio credential vars (bound to Settings tab entries)
        self.tw_sid   = tk.StringVar(value=TWILIO_SID)
        self.tw_token = tk.StringVar(value=TWILIO_TOKEN)
        self.tw_from  = tk.StringVar(value=TWILIO_FROM)

        # alert mode toggles
        self.do_call = tk.BooleanVar(value=True)
        self.do_sms  = tk.BooleanVar(value=True)

        self._styles()
        self._header()
        self._tabs()

    # ── TTK Styles ────────────────────────────────────────────────────────
    def _styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TNotebook", background=self.BG, borderwidth=0)
        s.configure("TNotebook.Tab", background=self.PANEL, foreground=self.SUB,
                    padding=[18,10], font=("Georgia",11,"bold"), borderwidth=0)
        s.map("TNotebook.Tab",
              background=[("selected", self.ACCENT)],
              foreground=[("selected", self.BG)])
        s.configure("Treeview", background=self.CARD, foreground=self.TEXT,
                    fieldbackground=self.CARD, rowheight=30, font=("Consolas",10))
        s.configure("Treeview.Heading", background=self.HDR, foreground=self.ACCENT,
                    font=("Georgia",10,"bold"), relief="flat")
        s.map("Treeview", background=[("selected","#1B4F82")])
        s.configure("Vertical.TScrollbar", background=self.BORDER,
                    troughcolor=self.CARD, arrowcolor=self.ACCENT)

    # ── Header bar ────────────────────────────────────────────────────────
    def _header(self):
        h = tk.Frame(self, bg=self.HDR, height=74)
        h.pack(fill="x"); h.pack_propagate(False)

        left = tk.Frame(h, bg=self.HDR)
        left.pack(side="left", padx=24, pady=10)
        tk.Label(left, text="⚓", font=("Arial",30), bg=self.HDR,
                 fg=self.ACCENT).pack(side="left", padx=(0,10))
        tk.Label(left, text="FISHERMAN SAFETY MONITORING SYSTEM",
                 font=("Georgia",16,"bold"), bg=self.HDR, fg=self.TEXT).pack(side="left")

        right = tk.Frame(h, bg=self.HDR)
        right.pack(side="right", padx=24)

        self.mode_lbl = tk.Label(right, text="", font=("Consolas",10,"bold"),
                                 bg=self.HDR, padx=10, pady=4)
        self.mode_lbl.pack(side="right", padx=(12,0))
        self._update_badge()

        self.clk = tk.StringVar()
        tk.Label(right, textvariable=self.clk, font=("Consolas",11),
                 bg=self.HDR, fg=self.SUB).pack(side="right")
        self._tick()

        tk.Frame(self, bg=self.ACCENT, height=2).pack(fill="x")

    def _update_badge(self):
        live = bool(self.tw_sid.get() and self.tw_token.get() and self.tw_from.get())
        if live and TWILIO_OK:
            self.mode_lbl.config(text="📡  LIVE TWILIO MODE", fg=self.GREEN, bg="#0D3320")
        elif not TWILIO_OK:
            self.mode_lbl.config(text="⚠️  twilio not installed", fg=self.RED, bg="#2D0A0A")
        else:
            self.mode_lbl.config(text="🔶  DEMO MODE", fg=self.WARN, bg="#2D1E00")

    def _tick(self):
        self.clk.set(datetime.now().strftime("📅 %d %b %Y   🕐 %H:%M:%S"))
        self.after(1000, self._tick)

    # ── Notebook tabs ─────────────────────────────────────────────────────
    def _tabs(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)

        self.t_reg = tk.Frame(nb, bg=self.BG)
        self.t_cg  = tk.Frame(nb, bg=self.BG)
        self.t_log = tk.Frame(nb, bg=self.BG)
        self.t_cfg = tk.Frame(nb, bg=self.BG)

        nb.add(self.t_reg, text="  🐟  Fisherman Registry  ")
        nb.add(self.t_cg,  text="  🚨  Coast Guard Alert   ")
        nb.add(self.t_log, text="  📋  Alert Log           ")
        nb.add(self.t_cfg, text="  ⚙️   Settings            ")

        self._build_registry()
        self._build_coastguard()
        self._build_alertlog()
        self._build_settings()

    # ════════════════════════════════════════════════════════
    #  TAB 1 — FISHERMAN REGISTRY
    # ════════════════════════════════════════════════════════
    def _build_registry(self):
        tab = self.t_reg

        # ── Left: registration form ──
        form = tk.Frame(tab, bg=self.PANEL, width=350)
        form.pack(side="left", fill="y", padx=(16,8), pady=16)
        form.pack_propagate(False)

        self._slabel(form, "➕  Register New Fisherman")

        self.rv = {}
        fields = [
            ("Full Name",                "name"),
            ("Phone  (+91XXXXXXXXXX)",   "phone"),
            ("Boat ID",                  "boat_id"),
            ("Home Port",                "home_port"),
            ("Last Known Latitude",      "lat"),
            ("Last Known Longitude",     "lon"),
        ]
        for label, key in fields:
            tk.Label(form, text=label, bg=self.PANEL, fg=self.SUB,
                     font=("Georgia",10)).pack(anchor="w", padx=20, pady=(10,2))
            v = tk.StringVar()
            tk.Entry(form, textvariable=v, bg=self.CARD, fg=self.TEXT,
                     font=("Consolas",11), insertbackground=self.ACCENT,
                     relief="flat").pack(fill="x", padx=20, ipady=7)
            self.rv[key] = v

        self._mkbtn(form, "✅  Register Fisherman", self._do_register,
                    self.ACCENT, self.BG).pack(fill="x", padx=20, pady=(20,6))
        self._mkbtn(form, "🗑  Clear Fields",
                    lambda: [v.set("") for v in self.rv.values()],
                    self.BORDER, self.SUB).pack(fill="x", padx=20)

        self.reg_st = tk.Label(form, text="", bg=self.PANEL,
                               font=("Consolas",10), wraplength=300)
        self.reg_st.pack(padx=20, pady=10)

        # ── Right: fishermen table ──
        rgt = tk.Frame(tab, bg=self.BG)
        rgt.pack(side="left", fill="both", expand=True, padx=(0,16), pady=16)
        self._slabel(rgt, "📋  Registered Fishermen")

        # search bar
        sb = tk.Frame(rgt, bg=self.CARD, pady=6, padx=10)
        sb.pack(fill="x", pady=(0,8))
        tk.Label(sb, text="🔍", bg=self.CARD, fg=self.SUB,
                 font=("Arial",13)).pack(side="left")
        self.sq = tk.StringVar()
        self.sq.trace("w", lambda *_: self._refresh_reg())
        tk.Entry(sb, textvariable=self.sq, bg=self.CARD, fg=self.TEXT,
                 font=("Consolas",11), insertbackground=self.ACCENT,
                 relief="flat", width=36).pack(side="left", padx=8)

        cols = ("id","name","phone","boat_id","home_port","lat","lon")
        hdrs = ["ID","Name","Phone","Boat ID","Home Port","Latitude","Longitude"]
        wds  = [80,160,145,120,120,100,100]

        self.rtree = ttk.Treeview(rgt, columns=cols, show="headings", selectmode="browse")
        for c,h,w in zip(cols,hdrs,wds):
            self.rtree.heading(c, text=h)
            self.rtree.column(c, width=w, anchor="center")

        vs = ttk.Scrollbar(rgt, orient="vertical", command=self.rtree.yview)
        self.rtree.configure(yscrollcommand=vs.set)
        self.rtree.pack(side="left", fill="both", expand=True)
        vs.pack(side="left", fill="y")

        self.reg_cnt = tk.Label(rgt, text="", bg=self.BG, fg=self.SUB,
                                font=("Consolas",10))
        self.reg_cnt.pack(anchor="e", pady=4)
        self._refresh_reg()

    def _do_register(self):
        try:
            name  = self.rv["name"].get().strip()
            phone = self.rv["phone"].get().strip()
            boat  = self.rv["boat_id"].get().strip()
            port  = self.rv["home_port"].get().strip()
            lat   = float(self.rv["lat"].get().strip())
            lon   = float(self.rv["lon"].get().strip())
        except ValueError:
            self.reg_st.config(text="⚠ Lat/Lon must be numbers.", fg=self.RED)
            return
        if not all([name, phone, boat, port]):
            self.reg_st.config(text="⚠ All fields are required.", fg=self.RED)
            return
        # ensure phone starts with +
        if not phone.startswith("+"):
            phone = "+" + phone
        self.fishermen.append({
            "id": generate_id(), "name": name, "phone": phone,
            "boat_id": boat, "home_port": port, "lat": lat, "lon": lon
        })
        self._refresh_reg()
        for v in self.rv.values(): v.set("")
        self.reg_st.config(text=f"✅ {name} registered successfully!", fg=self.GREEN)

    def _refresh_reg(self):
        q = self.sq.get().lower() if hasattr(self, "sq") else ""
        for r in self.rtree.get_children(): self.rtree.delete(r)
        n = 0
        for f in self.fishermen:
            haystack = (f["name"]+f["phone"]+f["home_port"]+
                        f["boat_id"]+f["id"]).lower()
            if q and q not in haystack: continue
            self.rtree.insert("","end", values=(
                f["id"], f["name"], f["phone"], f["boat_id"],
                f["home_port"], f"{f['lat']:.4f}", f"{f['lon']:.4f}"
            ))
            n += 1
        if hasattr(self, "reg_cnt"):
            self.reg_cnt.config(text=f"Showing {n} of {len(self.fishermen)} fishermen")

    # ════════════════════════════════════════════════════════
    #  TAB 2 — COAST GUARD ALERT
    # ════════════════════════════════════════════════════════
    def _build_coastguard(self):
        tab = self.t_cg

        # ── Control panel ──
        ctrl = tk.Frame(tab, bg=self.PANEL)
        ctrl.pack(fill="x", padx=16, pady=(16,0))
        self._slabel(ctrl, "🚨  Coast Guard Emergency Alert Panel")

        # Location input row
        loc_row = tk.Frame(ctrl, bg=self.PANEL)
        loc_row.pack(fill="x", padx=16, pady=(0,4))

        tk.Label(loc_row, text="Distress Latitude:", bg=self.PANEL,
                 fg=self.SUB, font=("Georgia",10)).pack(side="left")
        self.cg_lat = tk.StringVar()
        tk.Entry(loc_row, textvariable=self.cg_lat, bg=self.CARD, fg=self.TEXT,
                 font=("Consolas",13,"bold"), insertbackground=self.ACCENT,
                 relief="flat", width=16).pack(side="left", ipady=8, padx=(4,20))

        tk.Label(loc_row, text="Distress Longitude:", bg=self.PANEL,
                 fg=self.SUB, font=("Georgia",10)).pack(side="left")
        self.cg_lon = tk.StringVar()
        tk.Entry(loc_row, textvariable=self.cg_lon, bg=self.CARD, fg=self.TEXT,
                 font=("Consolas",13,"bold"), insertbackground=self.ACCENT,
                 relief="flat", width=16).pack(side="left", ipady=8, padx=(4,20))

        tk.Label(loc_row, text="Radius (km):", bg=self.PANEL,
                 fg=self.SUB, font=("Georgia",10)).pack(side="left")
        self.cg_rad = tk.StringVar(value="200")
        tk.Entry(loc_row, textvariable=self.cg_rad, bg=self.CARD, fg=self.TEXT,
                 font=("Consolas",12), insertbackground=self.ACCENT,
                 relief="flat", width=8).pack(side="left", ipady=8, padx=(4,0))

        # hint label
        tk.Label(ctrl,
                 text="  📌 Type coordinates manually or paste from IoT device  |  "
                      "Example:  Lat = 9.9312    Lon = 76.2673",
                 bg=self.PANEL, fg=self.SUB,
                 font=("Consolas",9)).pack(anchor="w", padx=16, pady=(0,8))

        # ── Alert mode checkboxes ──
        mode_row = tk.Frame(ctrl, bg=self.PANEL)
        mode_row.pack(anchor="w", padx=16, pady=(0,10))
        tk.Label(mode_row, text="Alert Mode:", bg=self.PANEL,
                 fg=self.SUB, font=("Georgia",10,"bold")).pack(side="left", padx=(0,12))

        for text, var, color in [
            ("📞  Voice Call (Phone rings with alarm)", self.do_call, self.GREEN),
            ("💬  SMS (Location details)",              self.do_sms,  self.ACCENT),
        ]:
            tk.Checkbutton(mode_row, text=text, variable=var,
                           bg=self.PANEL, fg=color, selectcolor=self.CARD,
                           activebackground=self.PANEL,
                           font=("Georgia",10,"bold")).pack(side="left", padx=12)

        # ── BIG SOS button ──
        sos_btn = tk.Button(ctrl,
                            text="🔴  SEND SOS — CALL & SMS ALL NEARBY FISHERMEN",
                            command=self._dispatch_alerts,
                            bg=self.RED, fg="white",
                            font=("Georgia",14,"bold"),
                            relief="flat", cursor="hand2",
                            padx=20, pady=16)
        sos_btn.pack(padx=16, pady=(4,16))
        # pulse effect on SOS button
        self._pulse(sos_btn)

        # ── Results table ──
        res = tk.Frame(tab, bg=self.BG)
        res.pack(fill="both", expand=True, padx=16, pady=(8,4))
        self._slabel(res, "📡  Nearby Fishermen — Alert Status")

        cols = ("name","phone","dist","port","boat","call_st","sms_st")
        hdrs = ["Name","Phone","Distance","Home Port","Boat ID","📞 Call","💬 SMS"]
        wds  = [155,145,105,115,115,175,175]

        self.cg_tree = ttk.Treeview(res, columns=cols, show="headings")
        for c,h,w in zip(cols,hdrs,wds):
            self.cg_tree.heading(c, text=h)
            self.cg_tree.column(c, width=w, anchor="center")

        vs2 = ttk.Scrollbar(res, orient="vertical", command=self.cg_tree.yview)
        self.cg_tree.configure(yscrollcommand=vs2.set)
        self.cg_tree.pack(side="left", fill="both", expand=True)
        vs2.pack(side="left", fill="y")

        self.cg_tree.tag_configure("live",  foreground=self.GREEN)
        self.cg_tree.tag_configure("demo",  foreground=self.WARN)
        self.cg_tree.tag_configure("fail",  foreground=self.RED)

        self.cg_sum = tk.Label(tab, text="", bg=self.BG, font=("Consolas",11),
                               fg=self.GREEN, wraplength=1200)
        self.cg_sum.pack(pady=6)

    def _pulse(self, btn, state=True):
        btn.config(bg="#FF4E50" if state else "#C0392B")
        self.after(700, lambda: self._pulse(btn, not state))

    # ── Dispatch alerts ────────────────────────────────────────────────
    def _dispatch_alerts(self):
        try:
            lat = float(self.cg_lat.get())
            lon = float(self.cg_lon.get())
            rad = float(self.cg_rad.get())
        except ValueError:
            messagebox.showerror("Input Error",
                "Please enter valid Latitude, Longitude and Radius.\n"
                "Or press '📍 Use Real-Time Location' to auto-fill.")
            return

        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            messagebox.showerror("Invalid Coordinates",
                "Latitude: -90 to 90  |  Longitude: -180 to 180")
            return

        if not self.do_call.get() and not self.do_sms.get():
            messagebox.showwarning("No Alert Mode",
                "Please select at least one alert mode:\n📞 Voice Call or 💬 SMS")
            return

        # clear previous results
        for r in self.cg_tree.get_children(): self.cg_tree.delete(r)
        self.cg_sum.config(
            text="⏳ Finding nearby fishermen and sending alerts...", fg=self.WARN)
        self.update_idletasks()

        # find nearby fishermen
        nearby = sorted(
            [(haversine_km(lat, lon, f["lat"], f["lon"]), f)
             for f in self.fishermen
             if haversine_km(lat, lon, f["lat"], f["lon"]) <= rad],
            key=lambda x: x[0]
        )

        if not nearby:
            self.cg_sum.config(
                text=f"⚠ No fishermen found within {rad} km of ({lat:.4f}, {lon:.4f}).",
                fg=self.RED)
            return

        # credentials
        sid   = self.tw_sid.get().strip()
        token = self.tw_token.get().strip()
        from_ = self.tw_from.get().strip()
        live  = bool(sid and token and from_) and TWILIO_OK
        ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        want_call = self.do_call.get()
        want_sms  = self.do_sms.get()

        def _worker():
            results = []
            for dist, f in nearby:
                sms_text  = build_sms_text(f["name"], dist, lat, lon)
                twiml     = build_voice_twiml(f["name"], dist, lat, lon)
                phone     = f["phone"]

                # ── Voice Call ──
                if want_call:
                    if live:
                        ok, detail = twilio_call(sid, token, from_, phone, twiml)
                        call_st = "✅ CALLED" if ok else f"❌ {detail[:30]}"
                        call_code = "CALLED" if ok else f"FAILED:{detail[:40]}"
                    else:
                        call_st = "🔶 DEMO CALL"; call_code = "DEMO"
                else:
                    call_st = "—"; call_code = "SKIPPED"

                # ── SMS ──
                if want_sms:
                    if live:
                        ok2, detail2 = twilio_sms(sid, token, from_, phone, sms_text)
                        sms_st  = "✅ SMS SENT" if ok2 else f"❌ {detail2[:30]}"
                        sms_code = "SENT" if ok2 else f"FAILED:{detail2[:40]}"
                    else:
                        sms_st = "🔶 DEMO SMS"; sms_code = "DEMO"
                else:
                    sms_st = "—"; sms_code = "SKIPPED"

                tag = "live" if live else "demo"
                results.append({
                    "dist": dist, "f": f,
                    "sms_text": sms_text, "twiml": twiml,
                    "call_st": call_st, "call_code": call_code,
                    "sms_st": sms_st, "sms_code": sms_code,
                    "tag": tag, "ts": ts
                })

            self.after(0, lambda: self._alerts_done(results, lat, lon, rad, live, ts))

        threading.Thread(target=_worker, daemon=True).start()

    def _alerts_done(self, results, lat, lon, rad, live, ts):
        calls_sent = sms_sent = 0
        for r in results:
            f = r["f"]
            self.cg_tree.insert("","end", tag=r["tag"], values=(
                f["name"], f["phone"], f"{r['dist']:.2f} km",
                f["home_port"], f["boat_id"],
                r["call_st"], r["sms_st"]
            ))
            self.alert_log.append({
                "timestamp":   ts,
                "name":        f["name"],
                "phone":       f["phone"],
                "distance_km": f"{r['dist']:.2f}",
                "alert_lat":   lat,
                "alert_lon":   lon,
                "call_status": r["call_code"],
                "sms_status":  r["sms_code"],
                "sms_text":    r["sms_text"],
                "mode":        "LIVE" if live else "DEMO",
            })
            if "CALLED" in r["call_code"]: calls_sent += 1
            if "SENT"   in r["sms_code"]:  sms_sent   += 1

        mode_note = (
            "LIVE TWILIO" if live else
            "DEMO MODE — add Twilio credentials in ⚙️ Settings to send real alerts"
        )
        self.cg_sum.config(
            text=(f"{'✅' if live else '🔶'} {len(results)} fishermen within {rad} km  |  "
                  f"📞 {calls_sent} calls made  |  💬 {sms_sent} SMS sent  |  "
                  f"{mode_note}  |  {ts}"),
            fg=self.GREEN if live else self.WARN)

        self._refresh_log()

        popup = (
            f"{'🚨 LIVE ALERTS SENT' if live else '🔶 DEMO MODE — No real alerts sent'}\n\n"
            f"Distress Location:  Lat {lat:.4f},  Lon {lon:.4f}\n"
            f"Search Radius:      {rad} km\n"
            f"Fishermen found:    {len(results)}\n"
            f"📞 Calls made:      {calls_sent}\n"
            f"💬 SMS sent:        {sms_sent}\n\n"
            + ("Check Alert Log tab for full details."
               if live else
               "Go to ⚙️ Settings tab and enter your\nTwilio credentials to send real alerts.")
        )
        messagebox.showinfo("SOS Alert Summary", popup)

    # ════════════════════════════════════════════════════════
    #  TAB 3 — ALERT LOG
    # ════════════════════════════════════════════════════════
    def _build_alertlog(self):
        tab = self.t_log
        self._slabel(tab, "📋  Complete Alert History")

        cols = ("timestamp","name","phone","dist","lat","lon","call","sms","mode")
        hdrs = ["Timestamp","Fisherman","Phone","Dist(km)","Lat","Lon","📞 Call","💬 SMS","Mode"]
        wds  = [160,140,135,80,95,95,110,110,65]

        self.ltree = ttk.Treeview(tab, columns=cols, show="headings")
        for c,h,w in zip(cols,hdrs,wds):
            self.ltree.heading(c, text=h)
            self.ltree.column(c, width=w, anchor="center")

        vs3 = ttk.Scrollbar(tab, orient="vertical", command=self.ltree.yview)
        self.ltree.configure(yscrollcommand=vs3.set)
        self.ltree.pack(side="left", fill="both", expand=True, padx=(16,0), pady=16)
        vs3.pack(side="left", fill="y", pady=16, padx=(0,4))

        # ── SMS preview pane ──
        pf = tk.Frame(tab, bg=self.PANEL, width=370)
        pf.pack(side="left", fill="y", padx=(0,16), pady=16)
        pf.pack_propagate(False)

        tk.Label(pf, text="📱  SMS Content Preview", bg=self.PANEL,
                 fg=self.ACCENT, font=("Georgia",12,"bold")
                 ).pack(padx=16, pady=(16,8), anchor="w")

        self.sms_box = tk.Text(pf, bg=self.CARD, fg=self.TEXT,
                               font=("Consolas",10), wrap="word",
                               relief="flat", state="disabled",
                               padx=12, pady=12)
        self.sms_box.pack(fill="both", expand=True, padx=12, pady=(0,8))
        self.ltree.bind("<<TreeviewSelect>>", self._preview_sms)

        tk.Label(pf, text="📞  Voice Message Preview", bg=self.PANEL,
                 fg=self.ACCENT, font=("Georgia",11,"bold")
                 ).pack(padx=16, pady=(8,4), anchor="w")

        self.call_box = tk.Text(pf, bg=self.CARD, fg=self.GREEN,
                                font=("Consolas",9), wrap="word",
                                relief="flat", state="disabled",
                                padx=12, pady=10, height=7)
        self.call_box.pack(fill="x", padx=12, pady=(0,8))

        self._mkbtn(pf, "💾  Export Log (CSV)", self._export,
                    self.ACCENT, self.BG).pack(fill="x", padx=12, pady=(0,12))

    def _refresh_log(self):
        for r in self.ltree.get_children(): self.ltree.delete(r)
        for e in reversed(self.alert_log):
            self.ltree.insert("","end", values=(
                e["timestamp"], e["name"], e["phone"],
                e["distance_km"], e["alert_lat"], e["alert_lon"],
                e["call_status"], e["sms_status"], e["mode"]
            ))

    def _preview_sms(self, _):
        sel = self.ltree.selection()
        if not sel: return
        idx = self.ltree.index(sel[0])
        rev = list(reversed(self.alert_log))
        if idx < len(rev):
            entry = rev[idx]
            # SMS preview
            self.sms_box.config(state="normal")
            self.sms_box.delete("1.0","end")
            self.sms_box.insert("end", entry["sms_text"])
            self.sms_box.config(state="disabled")
            # Voice preview (plain text version of what gets spoken)
            f = entry
            voice_preview = (
                f"[SPOKEN ALOUD BY TWILIO]\n\n"
                f"\"Warning! Warning! This is an emergency alert from the "
                f"Fisherman Safety Monitoring System. "
                f"A fisherman is in danger near latitude "
                f"{f['alert_lat']}, longitude {f['alert_lon']}. "
                f"Dear {f['name']}, you are approximately "
                f"{f['distance_km']} kilometres away. "
                f"Please go to their location immediately "
                f"or call Coast Guard on 112.\"\n\n"
                f"[Message repeats 3 times]"
            )
            self.call_box.config(state="normal")
            self.call_box.delete("1.0","end")
            self.call_box.insert("end", voice_preview)
            self.call_box.config(state="disabled")

    def _export(self):
        if not self.alert_log:
            messagebox.showinfo("No Data","No alerts have been sent yet.")
            return
        path = os.path.join(os.path.expanduser("~"), "fisherman_alert_log.csv")
        with open(path,"w",newline="") as f:
            w = csv.DictWriter(f, fieldnames=self.alert_log[0].keys())
            w.writeheader(); w.writerows(self.alert_log)
        messagebox.showinfo("Exported", f"Alert log saved to:\n{path}")

    # ════════════════════════════════════════════════════════
    #  TAB 4 — SETTINGS
    # ════════════════════════════════════════════════════════
    def _build_settings(self):
        tab = self.t_cfg
        self._slabel(tab, "⚙️   Twilio Configuration")

        card = tk.Frame(tab, bg=self.PANEL)
        card.pack(fill="x", padx=40, pady=16)

        # dependency check banner
        dep_color = self.GREEN if TWILIO_OK else self.RED
        dep_text  = ("✅  twilio library installed" if TWILIO_OK else
                     "❌  twilio not installed — run:  pip install twilio requests")
        tk.Label(card, text=dep_text, bg=self.PANEL, fg=dep_color,
                 font=("Consolas",11,"bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=20, pady=(16,12))

        # credential fields
        creds = [
            ("Account SID  (starts with AC...)", self.tw_sid,   False),
            ("Auth Token",                        self.tw_token, True),
            ("Twilio Phone Number  (+1XXXXXXXXXX)",self.tw_from, False),
        ]
        row = 1
        self._show_vars = []
        for label, var, secret in creds:
            tk.Label(card, text=label, bg=self.PANEL, fg=self.SUB,
                     font=("Georgia",10)).grid(row=row, column=0, sticky="w",
                                               padx=20, pady=(12,2))
            row += 1
            e = tk.Entry(card, textvariable=var, bg=self.CARD, fg=self.TEXT,
                         font=("Consolas",11), insertbackground=self.ACCENT,
                         relief="flat", width=52, show="*" if secret else "")
            e.grid(row=row, column=0, sticky="ew", padx=20, ipady=8)
            if secret:
                sv = tk.BooleanVar()
                self._show_vars.append((sv, e))
                tk.Checkbutton(card, text="Show", variable=sv,
                               command=lambda s=sv, en=e: en.config(
                                   show="" if s.get() else "*"),
                               bg=self.PANEL, fg=self.SUB, selectcolor=self.CARD,
                               activebackground=self.PANEL, font=("Georgia",9)
                               ).grid(row=row, column=1, padx=8)
            row += 1

        self._mkbtn(card, "💾  Save & Apply", self._save_cfg,
                    self.ACCENT, self.BG).grid(row=row, column=0, sticky="w",
                                               padx=20, pady=20)
        self.cfg_st = tk.Label(card, text="", bg=self.PANEL, font=("Consolas",10))
        self.cfg_st.grid(row=row+1, column=0, sticky="w", padx=20)

        # ── Help instructions ──
        help_frame = tk.Frame(tab, bg=self.CARD)
        help_frame.pack(fill="x", padx=40, pady=(0,20))

        instructions = """
📋  HOW TO SET UP TWILIO FREE ACCOUNT (10 minutes)

STEP 1:  Go to https://www.twilio.com/try-twilio and sign up free
         No credit card needed. You get $15 free credits (~300 calls/SMS)

STEP 2:  Verify your phone number during signup

STEP 3:  From the Twilio Console (console.twilio.com) copy:
           • Account SID   →  paste in field above
           • Auth Token    →  paste in field above
           • Phone Number  →  from Phone Numbers → Manage → Active Numbers

STEP 4:  Verify each fisherman's phone number (free trial requirement):
           Twilio Console → Phone Numbers → Verified Caller IDs → Add New
           They receive an OTP → enter it → number is verified ✅

STEP 5:  Paste credentials above → click 💾 Save & Apply
         Header will change to  📡 LIVE TWILIO MODE

📞  VOICE CALL:  Fisherman's phone RINGS. They hear the alarm message spoken
                 aloud in English (en-IN accent). Message repeats 3 times.

💬  SMS:         Fisherman receives a text with exact GPS coordinates
                 and Coast Guard number (112)

💡  DEMO MODE:   Without credentials everything works except actual
                 calls/SMS. Use this for testing the app logic.
"""
        tk.Label(help_frame, text=instructions, bg=self.CARD, fg=self.SUB,
                 font=("Consolas",10), justify="left", anchor="nw",
                 padx=20, pady=16).pack(fill="x")

    def _save_cfg(self):
        global TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM
        TWILIO_SID   = self.tw_sid.get().strip()
        TWILIO_TOKEN = self.tw_token.get().strip()
        TWILIO_FROM  = self.tw_from.get().strip()
        self._update_badge()
        live = bool(TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM) and TWILIO_OK
        self.cfg_st.config(
            text=f"✅ Saved. Mode: {'LIVE TWILIO' if live else 'DEMO'}",
            fg=self.GREEN if live else self.WARN)

    # ── Shared utilities ──────────────────────────────────────────────────
    def _slabel(self, parent, text):
        tk.Label(parent, text=text, bg=parent.cget("bg"), fg=self.ACCENT,
                 font=("Georgia",13,"bold")).pack(anchor="w", padx=16, pady=(14,8))

    def _mkbtn(self, parent, text, cmd, bg, fg):
        return tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                         font=("Georgia",10,"bold"), relief="flat",
                         cursor="hand2", padx=12, pady=10)


# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    App().mainloop()
    