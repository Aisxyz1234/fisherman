"""
Fisherman Safety Monitoring System  v4.0
==========================================
Coast Guard Desktop Application

What's new in v4:
  - Live fisherman locations pulled from Flask server every 60 seconds
  - Fishermen table shows REAL-TIME GPS positions + last update time
  - Distress location entered MANUALLY by Coast Guard (or paste from IoT device)
  - Twilio voice call + SMS to nearest fishermen
  - Demo mode if no credentials

Setup:
  pip install twilio requests flask flask-cors

Run order:
  1. python server.py          (keep running in background)
  2. python coast_guard_app.py (open this app)

Fishermen open on phone:
  http://YOUR_PC_IP:5000/track/FSH001
"""

import tkinter as tk
from tkinter import ttk, messagebox
import math, csv, os, random, threading, time
from datetime import datetime

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

# ── Configuration ──────────────────────────────────────────────────────────
SERVER_URL   = "http://127.0.0.1:5000"   # Flask server address
TWILIO_SID   = os.environ.get("TWILIO_SID",   "")
TWILIO_TOKEN = os.environ.get("TWILIO_TOKEN",  "")
TWILIO_FROM  = os.environ.get("TWILIO_FROM",   "")
POLL_INTERVAL = 30   # seconds between location refreshes

# ── Sample registered fishermen (static registry) ─────────────────────────
REGISTERED_FISHERMEN = [
    {"id":"FSH001","name":"Rajan Kumar",   "phone":"+919876543210","boat_id":"KL-01-F-1001","home_port":"Kochi"},
    {"id":"FSH002","name":"Murugan S",     "phone":"+919876543211","boat_id":"KL-02-F-2034","home_port":"Alappuzha"},
    {"id":"FSH003","name":"Sathish P",     "phone":"+919876543212","boat_id":"KL-04-F-3021","home_port":"Kollam"},
    {"id":"FSH004","name":"Biju Thomas",   "phone":"+919876543213","boat_id":"KL-06-F-4412","home_port":"Thrissur"},
    {"id":"FSH005","name":"Anwar Hussain", "phone":"+919876543214","boat_id":"KL-07-F-5561","home_port":"Kozhikode"},
    {"id":"FSH006","name":"Pradeep Nair",  "phone":"+919876543215","boat_id":"KL-09-F-6002","home_port":"Kannur"},
    {"id":"FSH007","name":"Suresh Pillai", "phone":"+919876543216","boat_id":"KL-11-F-7234","home_port":"Thiruvananthapuram"},
    {"id":"FSH008","name":"Dasan V",       "phone":"+919876543217","boat_id":"KL-12-F-8801","home_port":"Malappuram"},
    {"id":"FSH009","name":"Krishnan M",    "phone":"+919876543218","boat_id":"KL-03-F-9103","home_port":"Ernakulam"},
    {"id":"FSH010","name":"Joseph Antony", "phone":"+919876543219","boat_id":"KL-05-F-0234","home_port":"Kasaragod"},
]

# ── Helpers ────────────────────────────────────────────────────────────────

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2-lat1); dl = math.radians(lon2-lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def generate_id():
    return f"FSH{random.randint(100,999)}"

def build_sms(name, dist_km, lat, lon):
    # Google Maps link — fisherman taps this to navigate directly to victim
    maps_link = f"https://maps.google.com/?q={lat:.5f},{lon:.5f}"
    return (
        f"SOS EMERGENCY ALERT\n"
        f"A fisherman is in DANGER!\n"
        f"\n"
        f"Distress Location:\n"
        f"Lat: {lat:.5f}\n"
        f"Lon: {lon:.5f}\n"
        f"\n"
        f"Navigate here:\n"
        f"{maps_link}\n"
        f"\n"
        f"Dear {name}, you are {dist_km:.1f} km away.\n"
        f"Please go to their location immediately!\n"
        f"\n"
        f"Coast Guard: 112\n"
        f"-FishermanSafetySystem"
    )

def build_twiml(name, dist_km, lat, lon):
    # spoken message read aloud when fisherman picks up the call
    msg = (
        f"Warning! Warning! Warning! "
        f"This is an emergency alert from the Fisherman Safety Monitoring System. "
        f"A fisherman is in danger and needs immediate help. "
        f"The distress location is latitude {lat:.2f} and longitude {lon:.2f}. "
        f"Dear {name}, you are approximately {dist_km:.0f} kilometres away from the victim. "
        f"Please go to their location immediately or call the Coast Guard on 1 1 2. "
        f"I repeat. A fisherman is in danger at latitude {lat:.2f}, longitude {lon:.2f}. "
        f"You are {dist_km:.0f} kilometres away. "
        f"Go to their location now or call 1 1 2 for Coast Guard assistance. "
        f"An SMS with the exact location and Google Maps link has also been sent to you. "
        f"Please check your messages. "
        f"This message will now repeat one more time. "
    )
    return (
        f'<Response>'
        f'<Say voice="alice" language="en-IN" loop="2">{msg}</Say>'
        f'<Pause length="2"/>'
        f'<Say voice="alice" language="en-IN">'
        f'Emergency alert complete. Coast Guard number is 1 1 2. Check your SMS for the Google Maps location link. Thank you.'
        f'</Say>'
        f'</Response>'
    )

def twilio_call(sid, token, from_, to, twiml):
    if not TWILIO_OK:
        return False, "twilio not installed"
    try:
        c = TwilioClient(sid, token)
        call = c.calls.create(to=to, from_=from_, twiml=twiml)
        return True, call.sid
    except Exception as e:
        return False, str(e)

def twilio_sms(sid, token, from_, to, body):
    if not TWILIO_OK:
        return False, "twilio not installed"
    try:
        c = TwilioClient(sid, token)
        m = c.messages.create(to=to, from_=from_, body=body)
        return True, m.sid
    except Exception as e:
        return False, str(e)

def fetch_live_locations():
    """Pull latest fisherman GPS from Flask server."""
    if not REQUESTS_OK:
        return []
    try:
        r = requests.get(f"{SERVER_URL}/locations", timeout=5)
        if r.status_code == 200:
            return r.json()
    except:
        pass
    return []

def check_server():
    """Check if Flask server is running."""
    if not REQUESTS_OK:
        return False
    try:
        r = requests.get(f"{SERVER_URL}/", timeout=3)
        return r.status_code == 200
    except:
        return False


# ═══════════════════════════════════════════════════════════════════════════
#  MAIN APPLICATION
# ═══════════════════════════════════════════════════════════════════════════

class App(tk.Tk):
    BG     = "#0A1628"; PANEL  = "#0F2040"; CARD   = "#132847"
    ACCENT = "#00C6FF"; RED    = "#FF4E50"; GREEN  = "#00E676"
    WARN   = "#FFB300"; TEXT   = "#E8F4FD"; SUB    = "#7EB8D4"
    BORDER = "#1E3A5F"; HDR    = "#0D1F38"

    def __init__(self):
        super().__init__()
        self.title("Fisherman Safety Monitoring System  v4.0  —  Coast Guard")
        self.geometry("1380x880"); self.minsize(1100,720)
        self.configure(bg=self.BG)

        # data
        self.registered = list(REGISTERED_FISHERMEN)
        self.live_locs  = {}   # { id: {lat, lon, updated, ...} }
        self.alert_log  = []
        self.server_ok  = False

        # Twilio vars
        self.tw_sid   = tk.StringVar(value=TWILIO_SID)
        self.tw_token = tk.StringVar(value=TWILIO_TOKEN)
        self.tw_from  = tk.StringVar(value=TWILIO_FROM)
        self.tw_server= tk.StringVar(value=SERVER_URL)

        # alert mode
        self.do_call = tk.BooleanVar(value=True)
        self.do_sms  = tk.BooleanVar(value=True)

        self._styles(); self._header(); self._tabs()

        # start background tasks
        self._poll_locations()
        self._check_server_status()

    # ── Styles ───────────────────────────────────────────────────────────
    def _styles(self):
        s = ttk.Style(self); s.theme_use("clam")
        s.configure("TNotebook", background=self.BG, borderwidth=0)
        s.configure("TNotebook.Tab", background=self.PANEL, foreground=self.SUB,
                    padding=[18,10], font=("Georgia",11,"bold"), borderwidth=0)
        s.map("TNotebook.Tab",
              background=[("selected",self.ACCENT)], foreground=[("selected",self.BG)])
        s.configure("Treeview", background=self.CARD, foreground=self.TEXT,
                    fieldbackground=self.CARD, rowheight=30, font=("Consolas",10))
        s.configure("Treeview.Heading", background=self.HDR, foreground=self.ACCENT,
                    font=("Georgia",10,"bold"), relief="flat")
        s.map("Treeview", background=[("selected","#1B4F82")])
        s.configure("Vertical.TScrollbar", background=self.BORDER,
                    troughcolor=self.CARD, arrowcolor=self.ACCENT)

    # ── Header ───────────────────────────────────────────────────────────
    def _header(self):
        h = tk.Frame(self, bg=self.HDR, height=74)
        h.pack(fill="x"); h.pack_propagate(False)

        left = tk.Frame(h, bg=self.HDR)
        left.pack(side="left", padx=24, pady=10)
        tk.Label(left, text="⚓", font=("Arial",30), bg=self.HDR,
                 fg=self.ACCENT).pack(side="left", padx=(0,10))
        tk.Label(left, text="FISHERMAN SAFETY MONITORING SYSTEM  —  COAST GUARD",
                 font=("Georgia",15,"bold"), bg=self.HDR, fg=self.TEXT).pack(side="left")

        right = tk.Frame(h, bg=self.HDR)
        right.pack(side="right", padx=24)

        # server status indicator
        self.srv_lbl = tk.Label(right, text="", font=("Consolas",10,"bold"),
                                bg=self.HDR, padx=10, pady=4)
        self.srv_lbl.pack(side="right", padx=(8,0))

        # mode badge
        self.mode_lbl = tk.Label(right, text="", font=("Consolas",10,"bold"),
                                 bg=self.HDR, padx=10, pady=4)
        self.mode_lbl.pack(side="right", padx=(8,0))
        self._update_badge()

        self.clk = tk.StringVar()
        tk.Label(right, textvariable=self.clk, font=("Consolas",11),
                 bg=self.HDR, fg=self.SUB).pack(side="right")
        self._tick()

        tk.Frame(self, bg=self.ACCENT, height=2).pack(fill="x")

    def _update_badge(self):
        live = bool(self.tw_sid.get() and self.tw_token.get() and self.tw_from.get())
        if live and TWILIO_OK:
            self.mode_lbl.config(text="📡 LIVE TWILIO", fg=self.GREEN, bg="#0D3320")
        else:
            self.mode_lbl.config(text="🔶 DEMO MODE", fg=self.WARN, bg="#2D1E00")

    def _update_server_badge(self, ok):
        if ok:
            self.srv_lbl.config(text="🟢 SERVER ONLINE", fg=self.GREEN, bg="#0D3320")
        else:
            self.srv_lbl.config(text="🔴 SERVER OFFLINE", fg=self.RED, bg="#2D0A0A")

    def _tick(self):
        self.clk.set(datetime.now().strftime("📅 %d %b %Y   🕐 %H:%M:%S"))
        self.after(1000, self._tick)

    # ── Background: poll server for live locations ────────────────────────
    def _poll_locations(self):
        def _worker():
            locs = fetch_live_locations()
            self.after(0, lambda: self._on_locations(locs))
        threading.Thread(target=_worker, daemon=True).start()
        self.after(POLL_INTERVAL * 1000, self._poll_locations)

    def _on_locations(self, locs):
        for loc in locs:
            fid = loc.get("id","")
            if fid:
                self.live_locs[fid] = loc
        self._refresh_live_table()

    def _check_server_status(self):
        def _worker():
            ok = check_server()
            self.after(0, lambda: self._update_server_badge(ok))
        threading.Thread(target=_worker, daemon=True).start()
        self.after(10000, self._check_server_status)

    # ── Tabs ─────────────────────────────────────────────────────────────
    def _tabs(self):
        nb = ttk.Notebook(self); nb.pack(fill="both", expand=True)
        self.t_live = tk.Frame(nb, bg=self.BG)
        self.t_reg  = tk.Frame(nb, bg=self.BG)
        self.t_cg   = tk.Frame(nb, bg=self.BG)
        self.t_log  = tk.Frame(nb, bg=self.BG)
        self.t_cfg  = tk.Frame(nb, bg=self.BG)
        nb.add(self.t_live, text="  📡  Live Positions      ")
        nb.add(self.t_reg,  text="  🐟  Fisherman Registry  ")
        nb.add(self.t_cg,   text="  🚨  Send SOS Alert      ")
        nb.add(self.t_log,  text="  📋  Alert Log           ")
        nb.add(self.t_cfg,  text="  ⚙️   Settings            ")
        self._build_live()
        self._build_registry()
        self._build_coastguard()
        self._build_alertlog()
        self._build_settings()

    # ════════════════════════════════════════════════════════
    #  TAB 1 — LIVE POSITIONS
    # ════════════════════════════════════════════════════════
    def _build_live(self):
        tab = self.t_live

        # top bar
        top = tk.Frame(tab, bg=self.PANEL)
        top.pack(fill="x", padx=16, pady=(16,0))
        self._slabel(top, "📡  Real-Time Fisherman Positions")

        info_row = tk.Frame(top, bg=self.PANEL)
        info_row.pack(fill="x", padx=16, pady=(0,12))

        self.live_count = tk.Label(info_row, text="Fetching locations...",
                                   bg=self.PANEL, fg=self.WARN, font=("Consolas",11))
        self.live_count.pack(side="left")

        tk.Button(info_row, text="🔄  Refresh Now",
                  command=self._manual_refresh,
                  bg=self.ACCENT, fg=self.BG, font=("Georgia",10,"bold"),
                  relief="flat", cursor="hand2", padx=12, pady=6
                  ).pack(side="right", padx=16)

        self.last_refresh = tk.Label(info_row, text="", bg=self.PANEL,
                                     fg=self.SUB, font=("Consolas",10))
        self.last_refresh.pack(side="right")

        # live table
        cols = ("id","name","lat","lon","accuracy","updated","status")
        hdrs = ["ID","Name","Latitude","Longitude","Accuracy","Last Update","Status"]
        wds  = [80,160,120,120,90,160,120]

        self.live_tree = ttk.Treeview(tab, columns=cols, show="headings")
        for c,h,w in zip(cols,hdrs,wds):
            self.live_tree.heading(c, text=h)
            self.live_tree.column(c, width=w, anchor="center")

        vs = ttk.Scrollbar(tab, orient="vertical", command=self.live_tree.yview)
        self.live_tree.configure(yscrollcommand=vs.set)
        self.live_tree.pack(side="left", fill="both", expand=True, padx=(16,0), pady=12)
        vs.pack(side="left", fill="y", pady=12, padx=(0,16))

        self.live_tree.tag_configure("active",  foreground=self.GREEN)
        self.live_tree.tag_configure("stale",   foreground=self.WARN)
        self.live_tree.tag_configure("offline", foreground=self.RED)

        # instructions box
        inst = tk.Frame(tab, bg=self.PANEL)
        inst.pack(fill="x", padx=16, pady=(0,16))
        tk.Label(inst, bg=self.PANEL, fg=self.SUB, font=("Consolas",10),
                 justify="left", padx=16, pady=12,
                 text=(
"📱  HOW FISHERMEN SHARE THEIR LOCATION:\n\n"
"Each fisherman opens this link on their phone browser:\n"
f"      http://YOUR_PC_IP:5000/track/FSH001\n"
f"      http://YOUR_PC_IP:5000/track/FSH002   (different ID for each)\n\n"
"They press START TRACKING → their GPS updates here every 60 seconds automatically.\n"
"No app install needed. Works on any Android or iPhone with a browser.\n\n"
"🔍 Find your PC's IP:  Open Command Prompt → type:  ipconfig  → look for IPv4 Address"
                 )).pack(fill="x")

    def _manual_refresh(self):
        self.live_count.config(text="🔄 Refreshing...", fg=self.WARN)
        def _w():
            locs = fetch_live_locations()
            self.after(0, lambda: self._on_locations(locs))
            self.after(0, lambda: self.last_refresh.config(
                text=f"Last refresh: {datetime.now().strftime('%H:%M:%S')}"))
        threading.Thread(target=_w, daemon=True).start()

    def _refresh_live_table(self):
        for r in self.live_tree.get_children(): self.live_tree.delete(r)
        now = datetime.now()
        active = 0
        for fid, loc in self.live_locs.items():
            # determine staleness
            try:
                upd = datetime.strptime(loc["updated"], "%Y-%m-%d %H:%M:%S")
                age_min = (now - upd).seconds / 60
                if age_min < 3:
                    tag = "active"; st = "🟢 Active"
                elif age_min < 10:
                    tag = "stale";  st = f"🟡 {int(age_min)}m ago"
                else:
                    tag = "offline"; st = f"🔴 {int(age_min)}m ago"
                if tag == "active": active += 1
            except:
                tag = "stale"; st = "Unknown"; age_min = 99

            self.live_tree.insert("","end", tag=tag, values=(
                loc.get("id",""),
                loc.get("name",""),
                f"{loc.get('lat',0):.5f}",
                f"{loc.get('lon',0):.5f}",
                f"{loc.get('accuracy',0):.0f} m",
                loc.get("updated",""),
                st
            ))

        total = len(self.live_locs)
        self.live_count.config(
            text=f"🟢 {active} active  |  📡 {total} total fishermen tracked",
            fg=self.GREEN if active > 0 else self.WARN)
        self.last_refresh.config(
            text=f"Last refresh: {datetime.now().strftime('%H:%M:%S')}")

    # ════════════════════════════════════════════════════════
    #  TAB 2 — REGISTRY
    # ════════════════════════════════════════════════════════
    def _build_registry(self):
        tab = self.t_reg

        form = tk.Frame(tab, bg=self.PANEL, width=350)
        form.pack(side="left", fill="y", padx=(16,8), pady=16)
        form.pack_propagate(False)
        self._slabel(form, "➕  Register New Fisherman")

        self.rv = {}
        for label, key in [("Full Name","name"),("Phone (+91XXXXXXXXXX)","phone"),
                            ("Boat ID","boat_id"),("Home Port","home_port")]:
            tk.Label(form, text=label, bg=self.PANEL, fg=self.SUB,
                     font=("Georgia",10)).pack(anchor="w", padx=20, pady=(10,2))
            v = tk.StringVar()
            tk.Entry(form, textvariable=v, bg=self.CARD, fg=self.TEXT,
                     font=("Consolas",11), insertbackground=self.ACCENT,
                     relief="flat").pack(fill="x", padx=20, ipady=7)
            self.rv[key] = v

        self._mkbtn(form, "✅  Register", self._do_register,
                    self.ACCENT, self.BG).pack(fill="x", padx=20, pady=(18,6))
        self._mkbtn(form, "🗑  Clear",
                    lambda: [v.set("") for v in self.rv.values()],
                    self.BORDER, self.SUB).pack(fill="x", padx=20)
        self.reg_st = tk.Label(form, text="", bg=self.PANEL, font=("Consolas",10),
                               wraplength=300)
        self.reg_st.pack(padx=20, pady=10)

        # table
        rgt = tk.Frame(tab, bg=self.BG)
        rgt.pack(side="left", fill="both", expand=True, padx=(0,16), pady=16)
        self._slabel(rgt, "📋  All Registered Fishermen")

        cols = ("id","name","phone","boat_id","home_port","live_status")
        hdrs = ["ID","Name","Phone","Boat ID","Home Port","Live Status"]
        wds  = [80,160,145,120,120,160]
        self.rtree = ttk.Treeview(rgt, columns=cols, show="headings")
        for c,h,w in zip(cols,hdrs,wds):
            self.rtree.heading(c,text=h); self.rtree.column(c,width=w,anchor="center")
        vs = ttk.Scrollbar(rgt, orient="vertical", command=self.rtree.yview)
        self.rtree.configure(yscrollcommand=vs.set)
        self.rtree.pack(side="left", fill="both", expand=True)
        vs.pack(side="left", fill="y")
        self._refresh_reg()

    def _do_register(self):
        name  = self.rv["name"].get().strip()
        phone = self.rv["phone"].get().strip()
        boat  = self.rv["boat_id"].get().strip()
        port  = self.rv["home_port"].get().strip()
        if not all([name,phone,boat,port]):
            self.reg_st.config(text="⚠ All fields required.", fg=self.RED); return
        if not phone.startswith("+"): phone = "+" + phone
        self.registered.append({"id":generate_id(),"name":name,"phone":phone,
                                 "boat_id":boat,"home_port":port})
        self._refresh_reg()
        for v in self.rv.values(): v.set("")
        self.reg_st.config(text=f"✅ {name} registered!", fg=self.GREEN)

    def _refresh_reg(self):
        for r in self.rtree.get_children(): self.rtree.delete(r)
        for f in self.registered:
            fid = f["id"]
            if fid in self.live_locs:
                loc = self.live_locs[fid]
                live_st = f"🟢 {loc['updated'][11:]}"
            else:
                live_st = "⚪ No live data"
            self.rtree.insert("","end", values=(
                fid, f["name"], f["phone"], f["boat_id"], f["home_port"], live_st))

    # ════════════════════════════════════════════════════════
    #  TAB 3 — COAST GUARD / SEND SOS
    # ════════════════════════════════════════════════════════
    def _build_coastguard(self):
        tab = self.t_cg

        ctrl = tk.Frame(tab, bg=self.PANEL)
        ctrl.pack(fill="x", padx=16, pady=(16,0))
        self._slabel(ctrl, "🚨  Enter Distress Location & Send SOS")

        # ── Distress location input ──
        dist_frame = tk.Frame(ctrl, bg=self.CARD, padx=20, pady=16)
        dist_frame.pack(fill="x", padx=16, pady=(0,12))

        tk.Label(dist_frame,
                 text="📌  DISTRESS LOCATION  —  Type manually or paste from IoT device",
                 bg=self.CARD, fg=self.ACCENT,
                 font=("Georgia",11,"bold")).grid(row=0,column=0,columnspan=4,
                                                  sticky="w", pady=(0,12))

        tk.Label(dist_frame, text="Latitude:", bg=self.CARD, fg=self.SUB,
                 font=("Georgia",10)).grid(row=1,column=0,sticky="w",padx=(0,6))
        self.dist_lat = tk.StringVar()
        lat_entry = tk.Entry(dist_frame, textvariable=self.dist_lat, bg=self.BG,
                             fg=self.TEXT, font=("Consolas",14,"bold"),
                             insertbackground=self.ACCENT, relief="flat", width=18)
        lat_entry.grid(row=1,column=1,ipady=10,padx=(0,20))

        tk.Label(dist_frame, text="Longitude:", bg=self.CARD, fg=self.SUB,
                 font=("Georgia",10)).grid(row=1,column=2,sticky="w",padx=(0,6))
        self.dist_lon = tk.StringVar()
        lon_entry = tk.Entry(dist_frame, textvariable=self.dist_lon, bg=self.BG,
                             fg=self.TEXT, font=("Consolas",14,"bold"),
                             insertbackground=self.ACCENT, relief="flat", width=18)
        lon_entry.grid(row=1,column=3,ipady=10,padx=(0,20))

        # example hint
        tk.Label(dist_frame,
                 text="Example:  Lat = 9.9312    Lon = 76.2673   (from IoT device GPS output)",
                 bg=self.CARD, fg=self.SUB, font=("Consolas",9)
                 ).grid(row=2,column=0,columnspan=4,sticky="w",pady=(6,0))

        # radius
        radius_row = tk.Frame(ctrl, bg=self.PANEL)
        radius_row.pack(fill="x", padx=16, pady=(0,8))

        tk.Label(radius_row, text="Search Radius (km):", bg=self.PANEL,
                 fg=self.SUB, font=("Georgia",10)).pack(side="left")
        self.dist_rad = tk.StringVar(value="200")
        tk.Entry(radius_row, textvariable=self.dist_rad, bg=self.CARD,
                 fg=self.TEXT, font=("Consolas",12),
                 insertbackground=self.ACCENT, relief="flat", width=8
                 ).pack(side="left", ipady=7, padx=(6,20))

        tk.Label(radius_row, text="Alert Mode:", bg=self.PANEL,
                 fg=self.SUB, font=("Georgia",10,"bold")).pack(side="left", padx=(10,10))

        for text, var, color in [
            ("📞 Voice Call", self.do_call, self.GREEN),
            ("💬 SMS",        self.do_sms,  self.ACCENT),
        ]:
            tk.Checkbutton(radius_row, text=text, variable=var,
                           bg=self.PANEL, fg=color, selectcolor=self.CARD,
                           activebackground=self.PANEL,
                           font=("Georgia",10,"bold")).pack(side="left", padx=8)

        # ── SOS button ──
        sos = tk.Button(ctrl,
                        text="🔴  FIND NEARBY FISHERMEN & SEND SOS ALERT",
                        command=self._dispatch,
                        bg=self.RED, fg="white",
                        font=("Georgia",14,"bold"),
                        relief="flat", cursor="hand2",
                        padx=20, pady=16)
        sos.pack(padx=16, pady=(4,16))
        self._pulse(sos)

        # ── Results ──
        res = tk.Frame(tab, bg=self.BG)
        res.pack(fill="both", expand=True, padx=16, pady=(8,4))
        self._slabel(res, "📡  Nearby Fishermen — Real-Time Positions & Alert Status")

        cols = ("name","phone","dist","lat","lon","last_upd","call_st","sms_st")
        hdrs = ["Name","Phone","Distance","Live Lat","Live Lon","Last Update","📞 Call","💬 SMS"]
        wds  = [140,140,95,110,110,150,155,155]

        self.cg_tree = ttk.Treeview(res, columns=cols, show="headings")
        for c,h,w in zip(cols,hdrs,wds):
            self.cg_tree.heading(c,text=h); self.cg_tree.column(c,width=w,anchor="center")
        vs2 = ttk.Scrollbar(res, orient="vertical", command=self.cg_tree.yview)
        self.cg_tree.configure(yscrollcommand=vs2.set)
        self.cg_tree.pack(side="left", fill="both", expand=True)
        vs2.pack(side="left", fill="y")
        self.cg_tree.tag_configure("live", foreground=self.GREEN)
        self.cg_tree.tag_configure("demo", foreground=self.WARN)
        self.cg_tree.tag_configure("fail", foreground=self.RED)

        self.cg_sum = tk.Label(tab, text="", bg=self.BG, font=("Consolas",11),
                               fg=self.GREEN, wraplength=1300)
        self.cg_sum.pack(pady=6)

    def _pulse(self, btn, state=True):
        btn.config(bg="#FF4E50" if state else "#C0392B")
        self.after(700, lambda: self._pulse(btn, not state))

    def _dispatch(self):
        try:
            lat = float(self.dist_lat.get())
            lon = float(self.dist_lon.get())
            rad = float(self.dist_rad.get())
        except ValueError:
            messagebox.showerror("Input Error",
                "Please enter valid Latitude and Longitude numbers.\n\n"
                "Example:\n  Latitude:  9.9312\n  Longitude: 76.2673\n\n"
                "Copy these from your IoT device GPS output.")
            return

        if not (-90<=lat<=90 and -180<=lon<=180):
            messagebox.showerror("Invalid Coordinates","Lat: -90–90 | Lon: -180–180")
            return

        if not self.do_call.get() and not self.do_sms.get():
            messagebox.showwarning("No Mode","Select at least one: 📞 Voice Call or 💬 SMS")
            return

        for r in self.cg_tree.get_children(): self.cg_tree.delete(r)
        self.cg_sum.config(
            text="⏳ Using REAL-TIME fisherman positions to find nearest... sending alerts...",
            fg=self.WARN)
        self.update_idletasks()

        # Build full fisherman list with live GPS
        fishermen_with_loc = []
        for f in self.registered:
            fid = f["id"]
            if fid in self.live_locs:
                loc = self.live_locs[fid]
                fishermen_with_loc.append({
                    **f,
                    "lat":     loc["lat"],
                    "lon":     loc["lon"],
                    "updated": loc.get("updated",""),
                    "live":    True
                })
            # If no live location skip — we only alert those we can locate

        if not fishermen_with_loc:
            messagebox.showwarning("No Live Locations",
                "No fishermen have shared their real-time location yet.\n\n"
                "Ask fishermen to open the tracker link on their phone:\n"
                "http://YOUR_PC_IP:5000/track/FSH001\n\n"
                "Then press ▶ START TRACKING on their phone.")
            self.cg_sum.config(text="⚠ No live fisherman locations available.", fg=self.RED)
            return

        nearby = sorted(
            [(haversine_km(lat,lon,f["lat"],f["lon"]), f)
             for f in fishermen_with_loc
             if haversine_km(lat,lon,f["lat"],f["lon"]) <= rad],
            key=lambda x: x[0]
        )

        if not nearby:
            self.cg_sum.config(
                text=f"⚠ No fishermen within {rad} km of ({lat:.4f}, {lon:.4f}).",
                fg=self.RED)
            return

        sid   = self.tw_sid.get().strip()
        token = self.tw_token.get().strip()
        from_ = self.tw_from.get().strip()
        live  = bool(sid and token and from_) and TWILIO_OK
        ts    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        want_call = self.do_call.get()
        want_sms  = self.do_sms.get()

        def _worker():
            rows = []
            for dist, f in nearby:
                sms_text = build_sms(f["name"], dist, lat, lon)
                twiml    = build_twiml(f["name"], dist, lat, lon)
                phone    = f["phone"]

                if want_call:
                    if live:
                        ok, detail = twilio_call(sid, token, from_, phone, twiml)
                        call_st = "✅ CALLED" if ok else f"❌ {detail[:28]}"
                        call_code = "CALLED" if ok else f"FAILED"
                    else:
                        call_st = "🔶 DEMO CALL"; call_code = "DEMO"
                else:
                    call_st = "—"; call_code = "SKIP"

                if want_sms:
                    if live:
                        ok2, detail2 = twilio_sms(sid, token, from_, phone, sms_text)
                        sms_st  = "✅ SMS SENT" if ok2 else f"❌ {detail2[:28]}"
                        sms_code = "SENT" if ok2 else "FAILED"
                    else:
                        sms_st = "🔶 DEMO SMS"; sms_code = "DEMO"
                else:
                    sms_st = "—"; sms_code = "SKIP"

                rows.append({
                    "dist":dist,"f":f,
                    "sms_text":sms_text,
                    "call_st":call_st,"call_code":call_code,
                    "sms_st":sms_st,"sms_code":sms_code,
                    "tag":"live" if live else "demo","ts":ts
                })

            self.after(0, lambda: self._alerts_done(rows,lat,lon,rad,live,ts))

        threading.Thread(target=_worker, daemon=True).start()

    def _alerts_done(self, rows, lat, lon, rad, live, ts):
        calls_sent = sms_sent = 0
        for r in rows:
            f = r["f"]
            self.cg_tree.insert("","end", tag=r["tag"], values=(
                f["name"], f["phone"],
                f"{r['dist']:.2f} km",
                f"{f['lat']:.4f}", f"{f['lon']:.4f}",
                f.get("updated",""),
                r["call_st"], r["sms_st"]
            ))
            self.alert_log.append({
                "timestamp":   ts,
                "name":        f["name"],
                "phone":       f["phone"],
                "distance_km": f"{r['dist']:.2f}",
                "distress_lat":lat, "distress_lon":lon,
                "fish_lat":    f["lat"], "fish_lon": f["lon"],
                "call_status": r["call_code"],
                "sms_status":  r["sms_code"],
                "sms_text":    r["sms_text"],
                "mode":        "LIVE" if live else "DEMO",
            })
            if "CALLED" in r["call_code"]: calls_sent += 1
            if "SENT"   in r["sms_code"]:  sms_sent   += 1

        self._refresh_log()
        note = "LIVE TWILIO" if live else "DEMO — add Twilio credentials in ⚙️ Settings"
        self.cg_sum.config(
            text=(f"{'✅' if live else '🔶'} {len(rows)} nearby fishermen  |  "
                  f"📞 {calls_sent} calls  |  💬 {sms_sent} SMS  |  "
                  f"Distress: {lat:.4f},{lon:.4f}  |  {note}  |  {ts}"),
            fg=self.GREEN if live else self.WARN)

        messagebox.showinfo("SOS Alert Summary",
            f"{'🚨 LIVE ALERTS SENT' if live else '🔶 DEMO MODE'}\n\n"
            f"Distress:  Lat {lat:.4f},  Lon {lon:.4f}\n"
            f"Radius:    {rad} km\n"
            f"Found:     {len(rows)} fishermen\n"
            f"📞 Calls:  {calls_sent}\n"
            f"💬 SMS:    {sms_sent}\n\n"
            + ("" if live else
               "Enter Twilio credentials in ⚙️ Settings to send real alerts."))

    # ════════════════════════════════════════════════════════
    #  TAB 4 — ALERT LOG
    # ════════════════════════════════════════════════════════
    def _build_alertlog(self):
        tab = self.t_log
        self._slabel(tab, "📋  Alert History")

        cols = ("ts","name","phone","dist","d_lat","d_lon","call","sms","mode")
        hdrs = ["Timestamp","Fisherman","Phone","Dist","Distress Lat","Distress Lon",
                "📞 Call","💬 SMS","Mode"]
        wds  = [155,135,130,75,105,105,105,105,60]

        self.ltree = ttk.Treeview(tab, columns=cols, show="headings")
        for c,h,w in zip(cols,hdrs,wds):
            self.ltree.heading(c,text=h); self.ltree.column(c,width=w,anchor="center")
        vs3 = ttk.Scrollbar(tab, orient="vertical", command=self.ltree.yview)
        self.ltree.configure(yscrollcommand=vs3.set)
        self.ltree.pack(side="left", fill="both", expand=True, padx=(16,0), pady=16)
        vs3.pack(side="left", fill="y", pady=16, padx=(0,4))

        pf = tk.Frame(tab, bg=self.PANEL, width=380)
        pf.pack(side="left", fill="y", padx=(0,16), pady=16)
        pf.pack_propagate(False)

        tk.Label(pf, text="📱  SMS Content", bg=self.PANEL, fg=self.ACCENT,
                 font=("Georgia",12,"bold")).pack(padx=16, pady=(16,6), anchor="w")
        self.sms_box = tk.Text(pf, bg=self.CARD, fg=self.TEXT, font=("Consolas",10),
                               wrap="word", relief="flat", state="disabled",
                               padx=12, pady=12)
        self.sms_box.pack(fill="both", expand=True, padx=12, pady=(0,8))
        self.ltree.bind("<<TreeviewSelect>>", self._preview)

        self._mkbtn(pf,"💾  Export CSV", self._export,
                    self.ACCENT, self.BG).pack(fill="x", padx=12, pady=(0,12))

    def _refresh_log(self):
        for r in self.ltree.get_children(): self.ltree.delete(r)
        for e in reversed(self.alert_log):
            self.ltree.insert("","end", values=(
                e["timestamp"],e["name"],e["phone"],e["distance_km"],
                e["distress_lat"],e["distress_lon"],
                e["call_status"],e["sms_status"],e["mode"]))

    def _preview(self, _):
        sel = self.ltree.selection()
        if not sel: return
        idx = self.ltree.index(sel[0])
        rev = list(reversed(self.alert_log))
        if idx < len(rev):
            self.sms_box.config(state="normal")
            self.sms_box.delete("1.0","end")
            self.sms_box.insert("end", rev[idx]["sms_text"])
            self.sms_box.config(state="disabled")

    def _export(self):
        if not self.alert_log:
            messagebox.showinfo("No Data","No alerts sent yet."); return
        path = os.path.join(os.path.expanduser("~"),"fisherman_alert_log.csv")
        with open(path,"w",newline="") as f:
            w = csv.DictWriter(f, fieldnames=self.alert_log[0].keys())
            w.writeheader(); w.writerows(self.alert_log)
        messagebox.showinfo("Exported", f"Saved:\n{path}")

    # ════════════════════════════════════════════════════════
    #  TAB 5 — SETTINGS
    # ════════════════════════════════════════════════════════
    def _build_settings(self):
        tab = self.t_cfg
        self._slabel(tab, "⚙️   Configuration")

        card = tk.Frame(tab, bg=self.PANEL)
        card.pack(fill="x", padx=40, pady=16)

        # dependency status
        rows_info = [
            ("twilio library:",  "✅ Installed" if TWILIO_OK  else "❌ Run: pip install twilio",   TWILIO_OK),
            ("requests library:","✅ Installed" if REQUESTS_OK else "❌ Run: pip install requests", REQUESTS_OK),
        ]
        for i,(lbl,val,ok) in enumerate(rows_info):
            tk.Label(card, text=lbl, bg=self.PANEL, fg=self.SUB,
                     font=("Consolas",10)).grid(row=i,column=0,sticky="w",padx=20,pady=2)
            tk.Label(card, text=val, bg=self.PANEL,
                     fg=self.GREEN if ok else self.RED,
                     font=("Consolas",10,"bold")).grid(row=i,column=1,sticky="w",padx=8)

        # server URL
        tk.Label(card, text="Flask Server URL:", bg=self.PANEL, fg=self.SUB,
                 font=("Georgia",10)).grid(row=3,column=0,sticky="w",padx=20,pady=(16,2))
        tk.Entry(card, textvariable=self.tw_server, bg=self.CARD, fg=self.TEXT,
                 font=("Consolas",11), insertbackground=self.ACCENT,
                 relief="flat", width=40).grid(row=4,column=0,sticky="ew",padx=20,ipady=7)

        # Twilio creds
        creds = [
            ("Twilio Account SID  (starts with AC...)", self.tw_sid,   False),
            ("Twilio Auth Token",                        self.tw_token, True),
            ("Twilio Phone Number  (+1XXXXXXXXXX)",      self.tw_from,  False),
        ]
        row = 5
        for label, var, secret in creds:
            tk.Label(card, text=label, bg=self.PANEL, fg=self.SUB,
                     font=("Georgia",10)).grid(row=row,column=0,sticky="w",padx=20,pady=(12,2))
            row+=1
            e = tk.Entry(card, textvariable=var, bg=self.CARD, fg=self.TEXT,
                         font=("Consolas",11), insertbackground=self.ACCENT,
                         relief="flat", width=52, show="*" if secret else "")
            e.grid(row=row,column=0,sticky="ew",padx=20,ipady=8)
            if secret:
                sv = tk.BooleanVar()
                tk.Checkbutton(card, text="Show", variable=sv,
                               command=lambda s=sv,en=e: en.config(show="" if s.get() else "*"),
                               bg=self.PANEL, fg=self.SUB, selectcolor=self.CARD,
                               activebackground=self.PANEL, font=("Georgia",9)
                               ).grid(row=row,column=1,padx=8)
            row+=1

        self._mkbtn(card,"💾  Save & Apply", self._save_cfg,
                    self.ACCENT, self.BG).grid(row=row,column=0,sticky="w",padx=20,pady=16)
        self.cfg_st = tk.Label(card, text="", bg=self.PANEL, font=("Consolas",10))
        self.cfg_st.grid(row=row+1,column=0,sticky="w",padx=20)

        # help
        info = tk.Frame(tab, bg=self.CARD)
        info.pack(fill="x", padx=40, pady=(0,20))
        tk.Label(info, justify="left", anchor="nw", padx=20, pady=16,
                 bg=self.CARD, fg=self.SUB, font=("Consolas",10),
                 text=(
"📋  QUICK SETUP GUIDE\n\n"
"1.  pip install twilio requests flask flask-cors\n\n"
"2.  Run server:   python server.py\n"
"    Find your PC IP in Command Prompt:  ipconfig  (look for IPv4 Address)\n\n"
"3.  Share tracker link with each fisherman:\n"
"    http://YOUR_PC_IP:5000/track/FSH001\n"
"    http://YOUR_PC_IP:5000/track/FSH002  (different number per fisherman)\n\n"
"4.  Fisherman opens link on phone → presses ▶ START TRACKING\n"
"    Their GPS updates here every 60 seconds automatically\n\n"
"5.  Sign up free at twilio.com → get SID, Token, Phone Number\n"
"    Verify each fisherman's phone in Twilio Console\n"
"    Paste credentials above → Save & Apply\n\n"
"6.  In SOS Alert tab → type distress coordinates → click 🔴 SEND SOS\n"
"    App uses REAL-TIME fisherman positions to find nearest ones\n"
"    Twilio calls their phones with alarm + sends SMS with GPS coordinates"
                 )).pack(fill="x")

    def _save_cfg(self):
        global SERVER_URL, TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM
        SERVER_URL   = self.tw_server.get().strip()
        TWILIO_SID   = self.tw_sid.get().strip()
        TWILIO_TOKEN = self.tw_token.get().strip()
        TWILIO_FROM  = self.tw_from.get().strip()
        self._update_badge()
        live = bool(TWILIO_SID and TWILIO_TOKEN and TWILIO_FROM) and TWILIO_OK
        self.cfg_st.config(
            text=f"✅ Saved. Mode: {'LIVE TWILIO' if live else 'DEMO'}",
            fg=self.GREEN if live else self.WARN)

    # ── Shared utilities ──────────────────────────────────────────────────
    def _slabel(self, p, t):
        tk.Label(p, text=t, bg=p.cget("bg"), fg=self.ACCENT,
                 font=("Georgia",13,"bold")).pack(anchor="w", padx=16, pady=(14,8))

    def _mkbtn(self, p, t, cmd, bg, fg):
        return tk.Button(p, text=t, command=cmd, bg=bg, fg=fg,
                         font=("Georgia",10,"bold"), relief="flat",
                         cursor="hand2", padx=12, pady=10)


# ══════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    App().mainloop()