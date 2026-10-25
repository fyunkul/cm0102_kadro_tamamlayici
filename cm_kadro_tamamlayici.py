#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CM0102 Kadro Tamamlayıcı
========================
Oyuncusu eksik kulüplere, benzer itibarlı kulüplerdeki gerçek oyunculardan "klonlanıp" yeni isim,
doğum tarihi ve milliyetle oyuncu ekler. Gri oyuncuların oluşmasını önler.

Kullanım: dosyaya çift tıkla (ya da `python cm_kadro_tamamlayici.py`) -> pencere açılır.
Komut satırı (isteğe bağlı):
    python cm_kadro_tamamlayici.py report <DataKlasörü> [--nations Turkey] [--csv eksik.csv]
    python cm_kadro_tamamlayici.py fill   <DataKlasörü> --csv eksik.csv --out Data_yeni

Oyun KAPALIYKEN çalıştır. Eklenen oyuncular YENİ OYUNDA görünür; eski kayıtlar etkilenmez.
Yalnızca Python 3.8+ gerekir (ek kütüphane yok).
"""
import argparse, bisect, collections, csv, datetime, os, random, shutil, struct, sys

STAFF_R, NONPLAYER_R, PLAYER_R, PREF_R, CLUB_R, NAME_R, NATION_R, COMP_R = 110, 68, 70, 52, 581, 60, 290, 107
O_ID, O_FIRST, O_SECOND, O_COMMON, O_DOB, O_YOB, O_NAT1, O_NAT2 = 0, 4, 8, 12, 16, 24, 26, 30
O_CLUBJOB, O_JOBCLUB, O_PLAYERID, O_PREFID, O_NONPLAYERID, O_SQUADFOR = 57, 61, 97, 101, 105, 109
P_NUM, P_CA, P_POS, P_ATTR, P_ATTR_END = 4, 5, 15, 27, 69
FOOT_IDX = (21, 32)
C_NAME, C_NATION, C_DIV, C_REP, C_SQUAD = 4, 83, 87, 128, 215
BASE_YEAR = 2001
CHANGED_FILES = ('staff.dat', 'club.dat', 'nation.dat', 'index.dat')


def cstr(b):
    return bytes(b).split(b'\0')[0].decode('latin1')


# ============================================================================ veri
class Data:
    def __init__(self, folder):
        self.folder = folder
        self.index = bytearray(open(os.path.join(folder, 'index.dat'), 'rb').read())
        self.entries = []
        for i in range(len(self.index) // 67):
            e = self.index[i * 67:(i + 1) * 67]
            tid, cnt = struct.unpack_from('<ii', e, 59)
            self.entries.append(dict(pos=i * 67, name=cstr(e[8:59]), tid=tid, count=cnt))
        cnt = {e['tid']: e['count'] for e in self.entries}
        self.n_staff, self.n_nonplayer, self.n_player, self.n_pref = cnt[6], cnt[9], cnt[10], cnt[22]
        raw = open(os.path.join(folder, 'staff.dat'), 'rb').read()
        o = 0
        self.staff = bytearray(raw[o:o + self.n_staff * STAFF_R]); o += self.n_staff * STAFF_R
        self.nonplayer = bytearray(raw[o:o + self.n_nonplayer * NONPLAYER_R]); o += self.n_nonplayer * NONPLAYER_R
        self.player = bytearray(raw[o:o + self.n_player * PLAYER_R]); o += self.n_player * PLAYER_R
        self.pref = bytearray(raw[o:o + self.n_pref * PREF_R]); o += self.n_pref * PREF_R
        if o != len(raw):
            raise ValueError('staff.dat boyutu index.dat ile uyuşmuyor (%d != %d). Desteklenmeyen bir Data klasörü.' % (o, len(raw)))
        self.club = bytearray(open(os.path.join(folder, 'club.dat'), 'rb').read())
        self.n_club = len(self.club) // CLUB_R
        self.nation = bytearray(open(os.path.join(folder, 'nation.dat'), 'rb').read())
        self.divs = self._comp_names(os.path.join(folder, 'club_comp.dat'))
        self.first = self._names('first_names.dat')
        self.second = self._names('second_names.dat')
        self.nation_name = {}
        for i in range(len(self.nation) // NATION_R):
            r = self.nation[i * NATION_R:(i + 1) * NATION_R]
            self.nation_name[struct.unpack_from('<i', r, 0)[0]] = cstr(r[4:55])

    def _comp_names(self, path):
        d = open(path, 'rb').read(); out = {}
        for i in range(len(d) // COMP_R):
            r = d[i * COMP_R:(i + 1) * COMP_R]
            out[struct.unpack_from('<i', r, 0)[0]] = cstr(r[4:55])
        return out

    def _names(self, f):
        d = open(os.path.join(self.folder, f), 'rb').read(); out = []
        for i in range(len(d) // NAME_R):
            r = d[i * NAME_R:(i + 1) * NAME_R]
            out.append((struct.unpack_from('<i', r, 51)[0], struct.unpack_from('<i', r, 55)[0],
                        struct.unpack_from('<b', r, 59)[0]))
        return out

    def S(self, i): return self.staff[i * STAFF_R:(i + 1) * STAFF_R]
    def P(self, i): return self.player[i * PLAYER_R:(i + 1) * PLAYER_R]
    def C(self, i): return self.club[i * CLUB_R:(i + 1) * CLUB_R]

    def club_info(self, i):
        r = self.C(i)
        squad = list(struct.unpack_from('<50i', r, C_SQUAD))
        nat = struct.unpack_from('<i', r, C_NATION)[0]; div = struct.unpack_from('<i', r, C_DIV)[0]
        return dict(idx=i, id=struct.unpack_from('<i', r, 0)[0], name=cstr(r[C_NAME:55]),
                    nation=nat, nation_name=self.nation_name.get(nat, '?'),
                    div=div, div_name=self.divs.get(div, '(ligsiz)'),
                    rep=struct.unpack_from('<h', r, C_REP)[0], squad=squad,
                    players=sum(1 for x in squad if x >= 0), free=sum(1 for x in squad if x < 0))


# ============================================================================ üretim
def role_of(pos):
    g = {'GK': pos[0], 'DEF': max(pos[1], pos[2], pos[7]), 'MID': max(pos[3], pos[4], pos[5]), 'ATT': pos[6]}
    best = max(g.values())
    for r in ('GK', 'ATT', 'MID', 'DEF'):
        if g[r] == best:
            return r


def quotas(T):
    gk = max(2, round(T * 0.15)); att = round(T * 0.20); mid = round(T * 0.30)
    return {'GK': gk, 'ATT': att, 'MID': mid, 'DEF': T - gk - att - mid}


def build_donors(D):
    club_rep = {}
    for i in range(D.n_club):
        r = D.C(i); club_rep[struct.unpack_from('<i', r, 0)[0]] = struct.unpack_from('<h', r, C_REP)[0]
    pools = {r: [] for r in ('GK', 'DEF', 'MID', 'ATT')}
    for sid in range(D.n_staff):
        s = D.S(sid)
        pid = struct.unpack_from('<i', s, O_PLAYERID)[0]
        cj = struct.unpack_from('<i', s, O_CLUBJOB)[0]
        if pid < 0 or cj < 0 or s[O_JOBCLUB] != 11 or cj not in club_rep:
            continue
        p = D.P(pid)
        if sum(p[P_ATTR:P_ATTR_END]) < 150 or struct.unpack_from('<h', p, P_CA)[0] <= 0:
            continue
        pools[role_of(list(p[P_POS:P_POS + 12]))].append((club_rep[cj], sid))
    for r in pools:
        pools[r].sort()
    return pools


def pick_donor(pools, role, rep, rng, window=40):
    lst = pools[role]
    k = bisect.bisect_left(lst, (rep, -1))
    lo, hi = max(0, k - window // 2), min(len(lst), k + window // 2)
    return lst[rng.randrange(lo, hi)][1]


def name_pool(names, nation):
    ids = [(i, max(1, c)) for (i, n, c) in names if n == nation]
    if not ids:
        ids = [(i, max(1, c)) for (i, n, c) in names if n == -1] or [(i, 1) for (i, n, c) in names[:500]]
    return [i for i, _ in ids], [w for _, w in ids]


def rand_dob(donor_year, rng):
    year = max(BASE_YEAR - 37, min(BASE_YEAR - 16, donor_year + rng.randint(-2, 2)))
    leap = 1 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 0
    return year, rng.randrange(0, 365 + leap), leap


def planned_additions(c, target):
    """Bir kulübe kaç oyuncu eklenir (kadro dolu / yer yoksa sınırlı)."""
    return max(0, min(target - c['players'], c['free']))


def build_free_agents(D):
    """Kulübü olmayan gerçek oyuncular (dosya boyutunu değiştirmeden kullanılabilirler)."""
    in_squad = set()
    for i in range(D.n_club):
        in_squad.update(x for x in struct.unpack_from('<50i', D.C(i), C_SQUAD) if x >= 0)
    out = []
    for sid in range(D.n_staff):
        s = D.S(sid)
        pid = struct.unpack_from('<i', s, O_PLAYERID)[0]
        if pid < 0 or struct.unpack_from('<i', s, O_CLUBJOB)[0] >= 0 or s[O_JOBCLUB] != 11 or sid in in_squad:
            continue
        yob = struct.unpack_from('<h', s, O_YOB)[0]
        p = D.P(pid)
        ca = struct.unpack_from('<h', p, P_CA)[0]
        if ca <= 0 or not (BASE_YEAR - 37 <= yob <= BASE_YEAR - 16) or sum(p[P_ATTR:P_ATTR_END]) < 100:
            continue
        out.append([sid, pid, ca, role_of(list(p[P_POS:P_POS + 12])), struct.unpack_from('<i', s, O_NAT1)[0]])
    return out


def take_free_agent(fa, role, nat, ref_ca, rng):
    for pred in (lambda a: a[4] == nat and a[3] == role, lambda a: a[3] == role and a[4] == nat or a[3] == role,
                 lambda a: a[4] == nat):
        cand = [a for a in fa if pred(a)]
        if cand:
            cand.sort(key=lambda a: abs(a[2] - ref_ca))
            a = cand[rng.randrange(min(5, len(cand)))]
            fa.remove(a)
            return a
    return None


def fill_clubs(D, targets, out_dir, seed=2026, progress=None, mode='reuse'):
    """mode: 'reuse' = yalnızca kulübü olmayan mevcut oyuncuları kadroya kat (dosya boyutu değişmez, güvenli);
    'mixed' = önce onları kullan, yetmezse yeni oluştur; 'create' = hep yeni oluştur."""
    """targets: {kulüp_id: hedef_kadro}. Değişen dosyaları out_dir'e yazar. D bellekte değişir (tekrar yükle)."""
    rng = random.Random(seed)
    pools = build_donors(D)
    fa = build_free_agents(D) if mode != 'create' else None
    stats = collections.Counter()
    name_cache, nat_add = {}, collections.Counter()
    new_staff, new_player, new_pref, log = bytearray(), bytearray(), bytearray(), []
    n_staff, n_player = D.n_staff, D.n_player
    work = [i for i in range(D.n_club) if struct.unpack_from('<i', D.C(i), 0)[0] in targets]
    filled = 0
    for step, i in enumerate(work):
        if progress:
            progress(step, len(work))
        c = D.club_info(i)
        T = targets[c['id']]
        need = planned_additions(c, T)
        if need <= 0:
            continue
        have = [x for x in c['squad'] if x >= 0]
        free_slots = [k for k, x in enumerate(c['squad']) if x < 0]
        used_numbers, used_names, roles = set(), set(), collections.Counter()
        for sid in have:
            s = D.S(sid)
            used_names.add((struct.unpack_from('<i', s, O_FIRST)[0], struct.unpack_from('<i', s, O_SECOND)[0]))
            pid = struct.unpack_from('<i', s, O_PLAYERID)[0]
            if pid >= 0:
                p = D.P(pid); used_numbers.add(p[P_NUM]); roles[role_of(list(p[P_POS:P_POS + 12]))] += 1
        q, added, nat = quotas(T), collections.Counter(), c['nation']
        if nat not in name_cache:
            name_cache[nat] = (name_pool(D.first, nat), name_pool(D.second, nat))
        (fids, fw), (sids, sw) = name_cache[nat]
        slot = 0
        for n in range(need):
            role = max(('GK', 'DEF', 'MID', 'ATT'),
                       key=lambda r: (q[r] - roles[r] - added[r], r == 'GK', r == 'DEF'))
            donor = pick_donor(pools, role, c['rep'], rng)
            if fa is not None:
                ref_ca = struct.unpack_from('<h', D.P(struct.unpack_from('<i', D.S(donor), O_PLAYERID)[0]), P_CA)[0]
                got = take_free_agent(fa, role, nat, ref_ca, rng)
                if got is not None:
                    sid, pid = got[0], got[1]
                    added[role] += 1
                    struct.pack_into('<i', D.staff, sid * STAFF_R + O_CLUBJOB, c['id'])
                    D.staff[sid * STAFF_R + O_JOBCLUB] = 11
                    num = next((x for x in ((1, 12, 13) if role == 'GK' else range(2, 100)) if x not in used_numbers), 99)
                    used_numbers.add(num); D.player[pid * PLAYER_R + P_NUM] = num
                    struct.pack_into('<i', D.club, i * CLUB_R + C_SQUAD + free_slots[slot] * 4, sid)
                    slot += 1; stats['reused'] += 1
                    log.append((c['id'], c['name'], sid, -1, -1, role, got[2], 0))
                    continue
                if mode == 'reuse':
                    stats['short'] += 1
                    continue
            added[role] += 1
            stats['created'] += 1
            donor = donor
            ds = bytearray(D.S(donor)); dp = bytearray(D.P(struct.unpack_from('<i', ds, O_PLAYERID)[0]))
            sid, pid = n_staff, n_player
            n_staff += 1; n_player += 1
            for _ in range(20):
                fi = rng.choices(fids, fw)[0]; si = rng.choices(sids, sw)[0]
                if (fi, si) not in used_names:
                    break
            used_names.add((fi, si))
            year, day, leap = rand_dob(struct.unpack_from('<H', ds, O_DOB + 2)[0], rng)
            struct.pack_into('<i', ds, O_ID, sid)
            struct.pack_into('<i', ds, O_FIRST, fi); struct.pack_into('<i', ds, O_SECOND, si)
            struct.pack_into('<i', ds, O_COMMON, 0)
            struct.pack_into('<HHBBBB', ds, O_DOB, day, year, leap, 0, 0, 0)
            struct.pack_into('<h', ds, O_YOB, year)
            struct.pack_into('<i', ds, O_NAT1, nat); struct.pack_into('<i', ds, O_NAT2, -1)
            struct.pack_into('<i', ds, O_CLUBJOB, c['id']); ds[O_JOBCLUB] = 11
            struct.pack_into('<i', ds, O_PLAYERID, pid); struct.pack_into('<i', ds, O_PREFID, sid)
            struct.pack_into('<i', ds, O_NONPLAYERID, -1); ds[O_SQUADFOR] = 0
            struct.pack_into('<i', dp, 0, pid)
            num = next((x for x in ((1, 12, 13) if role == 'GK' else range(2, 100)) if x not in used_numbers), 99)
            used_numbers.add(num); dp[P_NUM] = num
            for k in range(P_ATTR, P_ATTR_END):
                if dp[k] > 0 and (k - P_ATTR) not in FOOT_IDX and rng.random() < 0.3:
                    dp[k] = max(1, min(20, dp[k] + rng.choice((-1, 1))))
            pref = bytearray(b'\xff' * PREF_R); struct.pack_into('<i', pref, 0, sid)
            new_staff += ds; new_player += dp; new_pref += pref
            struct.pack_into('<i', D.club, i * CLUB_R + C_SQUAD + free_slots[slot] * 4, sid)
            slot += 1
            nat_add[nat] += 1
            log.append((c['id'], c['name'], sid, fi, si, role, struct.unpack_from('<h', dp, P_CA)[0], year))
        filled += 1
    if progress:
        progress(len(work), len(work))
    os.makedirs(out_dir, exist_ok=True)
    ns, np_ = len(new_staff) // STAFF_R, len(new_player) // PLAYER_R
    raw = (bytes(D.staff) + bytes(new_staff) + bytes(D.nonplayer) + bytes(D.player) + bytes(new_player)
           + bytes(D.pref) + bytes(new_pref))
    open(os.path.join(out_dir, 'staff.dat'), 'wb').write(raw)
    open(os.path.join(out_dir, 'club.dat'), 'wb').write(bytes(D.club))
    nat = bytearray(D.nation)
    for k in range(len(nat) // NATION_R):
        nid = struct.unpack_from('<i', nat, k * NATION_R)[0]
        if nid in nat_add:
            struct.pack_into('<i', nat, k * NATION_R + 136, struct.unpack_from('<i', nat, k * NATION_R + 136)[0] + nat_add[nid])
    open(os.path.join(out_dir, 'nation.dat'), 'wb').write(bytes(nat))
    idx = bytearray(D.index)
    for e in D.entries:
        if e['tid'] in (6, 22):
            struct.pack_into('<i', idx, e['pos'] + 63, D.n_staff + ns)
        elif e['tid'] == 10:
            struct.pack_into('<i', idx, e['pos'] + 63, D.n_player + np_)
            struct.pack_into('<i', idx, e['pos'], (D.n_staff + ns) * STAFF_R)
        elif e['tid'] == 11:
            struct.pack_into('<i', idx, e['pos'], (D.n_staff + ns) * STAFF_R + D.n_nonplayer * NONPLAYER_R)
    open(os.path.join(out_dir, 'index.dat'), 'wb').write(bytes(idx))
    with open(os.path.join(out_dir, 'eklenen_oyuncular.csv'), 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['KulupId', 'Kulup', 'StaffNo', 'AdId', 'SoyadId', 'Rol', 'CA', 'DogumYili(Data)'])
        w.writerows(log)
    return dict(clubs=filled, players=ns + stats['reused'], reused=stats['reused'], created=stats['created'], short=stats['short'])


def backup_files(folder):
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    bdir = os.path.join(folder, 'Yedek_' + stamp)
    os.makedirs(bdir)
    for f in CHANGED_FILES:
        shutil.copy2(os.path.join(folder, f), os.path.join(bdir, f))
    return bdir


# ============================================================================ komut satırı
def cmd_report(a):
    D = Data(a.data)
    only = {x.strip().lower() for x in a.nations.split(',') if x.strip()} if a.nations else None
    rows = [D.club_info(i) for i in range(D.n_club)]
    rows = [c for c in rows if c['players'] < a.min]
    rows.sort(key=lambda c: (c['nation_name'], c['div_name'], c['name']))
    with open(a.csv, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['Sec(1/0)', 'KulupId', 'Kulup', 'Ulke', 'Lig', 'Itibar', 'MevcutOyuncu', 'HedefKadro'])
        for c in rows:
            on = c['div'] >= 0 and (only is None or c['nation_name'].lower() in only)
            w.writerow([1 if on else 0, c['id'], c['name'], c['nation_name'], c['div_name'], c['rep'], c['players'], max(a.min, a.target)])
    print('%d kulüp yazıldı -> %s' % (len(rows), a.csv))


def cmd_fill(a):
    sel = {}
    with open(a.csv, newline='', encoding='utf-8-sig') as f:
        rd = csv.reader(f, delimiter=';'); h = next(rd); ix = {n: i for i, n in enumerate(h)}
        for r in rd:
            if r and r[ix['Sec(1/0)']].strip() in ('1', 'x', 'X', 'evet'):
                sel[int(r[ix['KulupId']])] = int(r[ix['HedefKadro']])
    D = Data(a.data)
    res = fill_clubs(D, sel, a.out, a.seed, progress=None, mode=a.mode)
    print('%d kulüp, %d oyuncu (serbest:%d yeni:%d eksik:%d) -> %s' % (res['clubs'], res['players'], res['reused'], res['created'], res['short'], a.out))


# ============================================================================ pencere
def run_gui():
    import threading, queue
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    class App(tk.Tk):
        COLS = (('sec', '✔', 40, 'center'), ('name', 'Kulüp', 230, 'w'), ('nation', 'Ülke', 120, 'w'),
                ('div', 'Lig', 200, 'w'), ('rep', 'İtibar', 60, 'e'), ('players', 'Oyuncu', 60, 'e'),
                ('target', 'Hedef', 55, 'e'), ('add', 'Eklenecek', 70, 'e'))

        def __init__(self):
            super().__init__()
            self.title('CM0102 Kadro Tamamlayıcı')
            self.geometry('1040x700')
            self.D = None
            self.clubs = {}
            self.checked = set()
            self.targets = {}
            self.sort_key, self.sort_rev = 'name', False
            self.q = queue.Queue()
            self.busy = False
            self._build()
            default = r'E:\Games\Championship Manager 01-02\Data'
            self.v_folder.set(default if os.path.isdir(default) else '')
            self.after(100, self._poll)
            if self.v_folder.get():
                self.after(300, self.load)

        # ---- arayüz
        def _build(self):
            top = ttk.Frame(self, padding=6); top.pack(fill='x')
            ttk.Label(top, text='Data klasörü:').pack(side='left')
            self.v_folder = tk.StringVar()
            ttk.Entry(top, textvariable=self.v_folder).pack(side='left', fill='x', expand=True, padx=6)
            ttk.Button(top, text='Gözat…', command=self.browse).pack(side='left')
            self.btn_load = ttk.Button(top, text='Yükle', command=self.load); self.btn_load.pack(side='left', padx=(6, 0))

            fl = ttk.Frame(self, padding=(6, 0)); fl.pack(fill='x')
            self.v_nation, self.v_div, self.v_search = tk.StringVar(value='(hepsi)'), tk.StringVar(value='(hepsi)'), tk.StringVar()
            self.v_only, self.v_max = tk.BooleanVar(value=False), tk.IntVar(value=16)
            ttk.Label(fl, text='Ülke:').pack(side='left')
            self.cb_nation = ttk.Combobox(fl, textvariable=self.v_nation, state='readonly', width=18); self.cb_nation.pack(side='left', padx=4)
            ttk.Label(fl, text='Lig:').pack(side='left')
            self.cb_div = ttk.Combobox(fl, textvariable=self.v_div, state='readonly', width=26); self.cb_div.pack(side='left', padx=4)
            ttk.Label(fl, text='Ara:').pack(side='left')
            e = ttk.Entry(fl, textvariable=self.v_search, width=16); e.pack(side='left', padx=4)
            ttk.Checkbutton(fl, text='Sadece oyuncusu şundan az olanlar:', variable=self.v_only, command=self.refresh).pack(side='left', padx=(8, 0))
            ttk.Spinbox(fl, from_=0, to=50, textvariable=self.v_max, width=4, command=self.refresh).pack(side='left')
            for w in (self.cb_nation, self.cb_div):
                w.bind('<<ComboboxSelected>>', lambda ev: self.refresh())
            self.v_search.trace_add('write', lambda *a: self.refresh())
            self.v_max.trace_add('write', lambda *a: self.refresh())

            mid = ttk.Frame(self, padding=6); mid.pack(fill='both', expand=True)
            self.tree = ttk.Treeview(mid, columns=[c[0] for c in self.COLS], show='headings', selectmode='extended')
            for key, text, wid, anc in self.COLS:
                self.tree.heading(key, text=text, command=lambda k=key: self.sort_by(k))
                self.tree.column(key, width=wid, anchor=anc, stretch=(key in ('name', 'div')))
            vs = ttk.Scrollbar(mid, orient='vertical', command=self.tree.yview)
            self.tree.configure(yscrollcommand=vs.set)
            self.tree.pack(side='left', fill='both', expand=True); vs.pack(side='left', fill='y')
            self.tree.bind('<Double-1>', self.on_double)
            self.tree.bind('<space>', lambda ev: (self.toggle_selected(), 'break')[1])
            self.tree.tag_configure('checked', background='#d9f2d9')
            self.tree.tag_configure('none', foreground='#a00000')

            bar = ttk.Frame(self, padding=(6, 0)); bar.pack(fill='x')
            ttk.Button(bar, text='Listelenenleri işaretle', command=lambda: self.mark_visible(True)).pack(side='left')
            ttk.Button(bar, text='Listelenenlerin işaretini kaldır', command=lambda: self.mark_visible(False)).pack(side='left', padx=4)
            ttk.Button(bar, text='Tüm işaretleri kaldır', command=self.clear_marks).pack(side='left')
            ttk.Label(bar, text='   Hedef kadro:').pack(side='left')
            self.v_target = tk.IntVar(value=20)
            ttk.Spinbox(bar, from_=11, to=45, textvariable=self.v_target, width=4).pack(side='left', padx=4)
            ttk.Button(bar, text='Seçili (mavi) satırlara uygula', command=self.apply_target).pack(side='left')
            ttk.Button(bar, text='Tüm işaretlilere uygula', command=lambda: self.apply_target(all_checked=True)).pack(side='left', padx=4)

            out = ttk.LabelFrame(self, text='Çıktı', padding=6); out.pack(fill='x', padx=6, pady=6)
            self.v_mode = tk.StringVar(value='new'); self.v_create = tk.BooleanVar(value=False)
            r1 = ttk.Frame(out); r1.pack(fill='x')
            ttk.Radiobutton(r1, text='Yeni klasöre yaz (Data\'ya dokunma):', variable=self.v_mode, value='new').pack(side='left')
            self.v_out = tk.StringVar()
            ttk.Entry(r1, textvariable=self.v_out).pack(side='left', fill='x', expand=True, padx=6)
            ttk.Button(r1, text='Gözat…', command=self.browse_out).pack(side='left')
            ttk.Radiobutton(out, text='Doğrudan Data klasörüne yaz (önce Data içine otomatik yedek alınır)', variable=self.v_mode, value='inplace').pack(anchor='w')

            ttk.Checkbutton(out, text='Kulübü olmayan oyuncular yetmezse yeni oyuncu da üret (deneysel: dosya boyutu büyür)', variable=self.v_create).pack(anchor='w')
            bt = ttk.Frame(self, padding=(6, 0, 6, 6)); bt.pack(fill='x')
            self.v_info = tk.StringVar(value='Data klasörünü seçip Yükle\'ye bas.')
            ttk.Label(bt, textvariable=self.v_info).pack(side='left')
            self.btn_run = ttk.Button(bt, text='Oyuncuları ekle', command=self.run, state='disabled'); self.btn_run.pack(side='right')
            self.pb = ttk.Progressbar(bt, length=180); self.pb.pack(side='right', padx=8)

        # ---- yardımcılar
        def browse(self):
            d = filedialog.askdirectory(title='Data klasörünü seç', initialdir=self.v_folder.get() or None)
            if d:
                self.v_folder.set(os.path.normpath(d)); self.load()

        def browse_out(self):
            d = filedialog.askdirectory(title='Çıktı klasörü')
            if d:
                self.v_out.set(os.path.normpath(d))

        def set_busy(self, b, msg=None):
            self.busy = b
            for w in (self.btn_load, self.btn_run):
                w.configure(state='disabled' if b else 'normal')
            if msg:
                self.v_info.set(msg)

        def load(self):
            folder = self.v_folder.get().strip()
            if not os.path.isfile(os.path.join(folder, 'staff.dat')):
                messagebox.showerror('Hata', 'Bu klasörde staff.dat bulunamadı.'); return
            if self.busy:
                return
            self.set_busy(True, 'Yükleniyor… (birkaç saniye)')
            if not self.v_out.get():
                self.v_out.set(os.path.join(os.path.dirname(folder.rstrip('\\/')), 'Data_yeni'))

            def work():
                try:
                    self.q.put(('loaded', Data(folder)))
                except Exception as ex:
                    self.q.put(('error', 'Yükleme hatası: %s' % ex))
            threading.Thread(target=work, daemon=True).start()

        def on_loaded(self, D):
            self.D = D
            self.clubs = {}
            for i in range(D.n_club):
                c = D.club_info(i); self.clubs[c['id']] = c
            self.checked.clear(); self.targets = {cid: self.v_target.get() for cid in self.clubs}
            nations = sorted({c['nation_name'] for c in self.clubs.values()})
            divs = sorted({c['div_name'] for c in self.clubs.values()})
            self.cb_nation['values'] = ['(hepsi)'] + nations
            self.cb_div['values'] = ['(hepsi)'] + divs
            self.v_nation.set('(hepsi)'); self.v_div.set('(hepsi)')
            self.set_busy(False)
            self.btn_run.configure(state='normal')
            self.refresh()

        def visible_ids(self):
            n, dv, s = self.v_nation.get(), self.v_div.get(), self.v_search.get().strip().lower()
            try:
                mx = self.v_max.get()
            except tk.TclError:
                mx = 16
            out = []
            for cid, c in self.clubs.items():
                if n != '(hepsi)' and c['nation_name'] != n: continue
                if dv != '(hepsi)' and c['div_name'] != dv: continue
                if s and s not in c['name'].lower(): continue
                if self.v_only.get() and c['players'] >= mx: continue
                out.append(cid)
            return out

        def row_values(self, cid):
            c = self.clubs[cid]; t = self.targets.get(cid, 20)
            return ('✔' if cid in self.checked else '', c['name'], c['nation_name'], c['div_name'], c['rep'],
                    c['players'], t, planned_additions(c, t))

        def refresh(self):
            if not self.clubs:
                return
            ids = self.visible_ids()
            keyidx = {k: i for i, (k, *_r) in enumerate(self.COLS)}[self.sort_key]
            ids.sort(key=lambda cid: (self.row_values(cid)[keyidx] if not isinstance(self.row_values(cid)[keyidx], str)
                                      else self.row_values(cid)[keyidx].lower()), reverse=self.sort_rev)
            self.tree.delete(*self.tree.get_children())
            for cid in ids:
                tags = []
                if cid in self.checked: tags.append('checked')
                if self.clubs[cid]['players'] == 0: tags.append('none')
                self.tree.insert('', 'end', iid=str(cid), values=self.row_values(cid), tags=tags)
            self.update_info(len(ids))

        def update_info(self, shown=None):
            add = sum(planned_additions(self.clubs[c], self.targets.get(c, 20)) for c in self.checked)
            self.v_info.set('Listelenen: %s kulüp | İşaretli: %d kulüp | Eklenecek: %d oyuncu' %
                            (shown if shown is not None else len(self.tree.get_children()), len(self.checked), add))

        def sort_by(self, key):
            if key == self.sort_key: self.sort_rev = not self.sort_rev
            else: self.sort_key, self.sort_rev = key, False
            self.refresh()

        def refresh_row(self, cid):
            if self.tree.exists(str(cid)):
                tags = (['checked'] if cid in self.checked else []) + (['none'] if self.clubs[cid]['players'] == 0 else [])
                self.tree.item(str(cid), values=self.row_values(cid), tags=tags)

        def on_double(self, ev):
            if self.tree.identify_region(ev.x, ev.y) != 'cell': return
            iid = self.tree.identify_row(ev.y)
            if iid:
                cid = int(iid)
                self.checked.symmetric_difference_update({cid}); self.refresh_row(cid); self.update_info()

        def toggle_selected(self):
            for iid in self.tree.selection():
                cid = int(iid); self.checked.symmetric_difference_update({cid}); self.refresh_row(cid)
            self.update_info()

        def mark_visible(self, on):
            for cid in self.visible_ids():
                (self.checked.add if on else self.checked.discard)(cid)
            self.refresh()

        def clear_marks(self):
            self.checked.clear(); self.refresh()

        def apply_target(self, all_checked=False):
            try:
                t = int(self.v_target.get())
            except tk.TclError:
                return
            ids = list(self.checked) if all_checked else [int(i) for i in self.tree.selection()]
            for cid in ids:
                self.targets[cid] = t
            self.refresh()

        # ---- çalıştır
        def run(self):
            if self.busy or not self.D: return
            if not self.checked:
                messagebox.showinfo('Bilgi', 'Önce kulüp işaretle (satıra çift tıkla ya da Listelenenleri işaretle).'); return
            tg = {cid: self.targets.get(cid, 20) for cid in self.checked}
            add = sum(planned_additions(self.clubs[c], t) for c, t in tg.items())
            if add == 0:
                messagebox.showinfo('Bilgi', 'İşaretli kulüplerin kadroları zaten hedefte.'); return
            folder = self.v_folder.get().strip()
            inplace = self.v_mode.get() == 'inplace'
            out = folder if inplace else self.v_out.get().strip()
            if not out:
                messagebox.showerror('Hata', 'Çıktı klasörü boş.'); return
            msg = '%d kulübe toplam %d oyuncu eklenecek.\n\n' % (len(tg), add)
            msg += ('Dosyalar doğrudan Data klasörüne yazılacak (önce yedek alınır).\n' if inplace
                    else 'Dosyalar şu klasöre yazılacak:\n%s\n' % out)
            msg += '\nOyun KAPALI olmalı. Devam edilsin mi?'
            if not messagebox.askyesno('Onay', msg): return
            self.set_busy(True, 'Çalışıyor…'); self.pb.configure(value=0, maximum=100)
            seed = 2026

            def work():
                try:
                    bdir = backup_files(folder) if inplace else None
                    res = fill_clubs(self.D, tg, out, seed, progress=lambda s, n: self.q.put(('prog', s, n)), mode=('mixed' if self.v_create.get() else 'reuse'))
                    self.q.put(('done', res, out, bdir, inplace))
                except Exception as ex:
                    self.q.put(('error', 'Hata: %s' % ex))
            threading.Thread(target=work, daemon=True).start()

        def _poll(self):
            try:
                while True:
                    m = self.q.get_nowait()
                    if m[0] == 'loaded': self.on_loaded(m[1])
                    elif m[0] == 'error':
                        self.set_busy(False); self.btn_run.configure(state='normal' if self.D else 'disabled')
                        messagebox.showerror('Hata', m[1])
                    elif m[0] == 'prog':
                        self.pb.configure(value=100.0 * m[1] / max(1, m[2]))
                    elif m[0] == 'done':
                        res, out, bdir, inplace = m[1], m[2], m[3], m[4]
                        self.pb.configure(value=100)
                        txt = '%d kulüp, %d oyuncu eklendi (serbest oyuncudan: %d, yeni üretilen: %d).\n' % (res['clubs'], res['players'], res['reused'], res['created'])
                        if res['short']: txt += 'UYARI: %d kadro yeri doldurulamadı (yeterli serbest oyuncu yok).\n' % res['short']
                        txt += '\n'
                        txt += ('Data klasörüne yazıldı. Eski dosyaların yedeği:\n%s\n' % bdir if inplace
                                else 'Çıktı klasörü:\n%s\n\nBu klasördeki staff.dat, club.dat, nation.dat ve index.dat dosyalarını Data klasörüne kopyala.\n' % out)
                        txt += '\nEklenen oyuncular yeni oyunda görünür.'
                        messagebox.showinfo('Tamam', txt)
                        self.set_busy(False)
                        if inplace: self.load()      # tablo güncellensin
            except queue.Empty:
                pass
            self.after(100, self._poll)

    App().mainloop()


def main():
    if len(sys.argv) == 1:
        run_gui(); return
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd', required=True)
    r = sub.add_parser('report'); r.add_argument('data'); r.add_argument('--min', type=int, default=16)
    r.add_argument('--target', type=int, default=20); r.add_argument('--csv', default='eksik_kulupler.csv')
    r.add_argument('--nations', default='')
    f = sub.add_parser('fill'); f.add_argument('data'); f.add_argument('--csv', default='eksik_kulupler.csv')
    f.add_argument('--out', default='Data_yeni'); f.add_argument('--mode', default='reuse', choices=['reuse', 'mixed', 'create']); f.add_argument('--seed', type=int, default=2026)
    sub.add_parser('gui')
    a = p.parse_args()
    {'report': cmd_report, 'fill': cmd_fill, 'gui': lambda a: run_gui()}[a.cmd](a)


if __name__ == '__main__':
    main()
