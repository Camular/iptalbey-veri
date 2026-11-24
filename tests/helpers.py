"""Testler için küçük katalog ve sahte (fake) GitHub/git/Gemini nesneleri."""

from __future__ import annotations

import copy
import datetime as dt
import json
import shutil
from pathlib import Path

import fiyat_kontrol as fk

REPO = Path(__file__).resolve().parent.parent
SPOTIFY_URL = "https://www.spotify.com/tr/premium/"
EXXEN_URL = "https://www.exxen.com/tr/paketler"
TURKCELL_URL = "https://www.turkcell.com.tr/paket/x"


def plan(pid, ad, seviye, fiyat, url, dogrulandi=True, periyot="aylik"):
    return {
        "id": pid,
        "ad": ad,
        "seviye": seviye,
        "fiyat_tl": fiyat,
        "periyot": periyot,
        "ogrenci": False,
        "onceki_fiyat_tl": None,
        "gecerlilik": None,
        "kaynak": url or "https://example.com/haber",
        "kontrol_tarihi": "2026-11-01",
        "dogrulandi": dogrulandi,
        "kaynak_notu": None,
        "izleme_url": url,
        "degisim_turu": None,
        "degisim_surumu": None,
    }


def catalog() -> dict:
    return {
        "sema_surumu": 1,
        "surum": 1,
        "guncelleme": "2026-11-01",
        "servisler": [
            {
                "id": "spotify",
                "ad": "Spotify",
                "kategori": "muzik",
                "planlar": [
                    plan("bireysel", "Bireysel", 1, 115, SPOTIFY_URL),
                    plan("aile", "Aile", 3, 199, SPOTIFY_URL),
                ],
            },
            {
                "id": "exxen",
                "ad": "Exxen",
                "kategori": "spor",
                "planlar": [
                    plan("reklamli", "Reklamlı", 1, 270.5, EXXEN_URL, dogrulandi=False),
                ],
            },
            {
                "id": "hbo-max",
                "ad": "HBO Max",
                "kategori": "video",
                "planlar": [
                    plan("standart", "Standart", 1, 229.9, None),
                ],
            },
        ],
        "operator_paketleri": [
            {
                "id": "turkcell-x",
                "operator": "Turkcell",
                "ad": "Turkcell X",
                "fiyat_tl": 500,
                "periyot": "aylik",
                "icerir": [{"servis": "spotify", "plan": "bireysel"}],
                "kaynak": TURKCELL_URL,
                "kontrol_tarihi": "2026-11-01",
                "dogrulandi": True,
                "izleme_url": TURKCELL_URL,
                "kaynak_notu": "12 ay taahhütlü",
            }
        ],
    }


def make_root(tmp_path: Path, cat: dict | None = None, guides: dict | None = None) -> Path:
    root = tmp_path / "veri"
    (root / "sema").mkdir(parents=True)
    for name in ("fiyatlar.schema.json", "iptal-rehberleri.schema.json"):
        shutil.copy(REPO / "sema" / name, root / "sema" / name)
    (root / "fiyatlar.json").write_text(fk.dump_json(cat or catalog()), encoding="utf-8")
    guides = guides or {"sema_surumu": 1, "surum": 1, "guncelleme": "2026-11-01", "rehberler": []}
    (root / "iptal-rehberleri.json").write_text(fk.dump_json(guides), encoding="utf-8")
    return root


SPOTIFY_HTML = (
    "<html><body><h2>Bireysel</h2><p>İlk 1 ay boyunca ücretsiz, sonra ayda ₺{b}.</p>"
    "<h2>Aile</h2><p>Sonra ayda ₺{a}</p></body></html>"
)
EXXEN_HTML = "<html><body><p>Reklamlı paket aylık {r} TL</p></body></html>"
TURKCELL_HTML = "<html><body><p>12 ay taahhütle aylık {t}TL, taahhütsüz 750TL</p></body></html>"


def pages(b="115", a="199", r="270,50", t="500") -> dict[str, str]:
    return {
        SPOTIFY_URL: SPOTIFY_HTML.format(b=b, a=a),
        EXXEN_URL: EXXEN_HTML.format(r=r),
        TURKCELL_URL: TURKCELL_HTML.format(t=t),
    }


def answer(key, price, quote, changed, guven=0.95, periyot="aylik"):
    return {
        "plan_id": key,
        "degisti": changed,
        "yeni_fiyat_tl": price,
        "periyot": periyot,
        "kanit_alinti": quote,
        "guven": guven,
    }


class FakeGemini:
    """URL'ye göre hazır yanıt döndürür; çağrıları sayar."""

    def __init__(self, answers_by_url: dict[str, list[dict]] | None = None, fail: bool = False):
        self.answers_by_url = answers_by_url or {}
        self.fail = fail
        self.model = None
        self.calls: list[str] = []

    def generate_json(self, prompt: str, schema: dict) -> dict:
        url = next(u for u in (SPOTIFY_URL, EXXEN_URL, TURKCELL_URL) if f"kaynak: {u}" in prompt)
        self.calls.append(url)
        if self.fail:
            raise fk.GeminiUnavailable("HTTP 429 (gemini-test)", detail="Quota exceeded for project 123456")
        self.model = "gemini-test"
        return {"planlar": self.answers_by_url.get(url, [])}


def default_answers(**override) -> dict[str, list[dict]]:
    """Hiçbir şey değişmemiş, her şey yüksek güvenle doğrulanmış yanıtlar."""
    data = {
        SPOTIFY_URL: [
            answer("spotify/bireysel", 115, "sonra ayda ₺115", False),
            answer("spotify/aile", 199, "Sonra ayda ₺199", False),
        ],
        EXXEN_URL: [answer("exxen/reklamli", 270.5, "Reklamlı paket aylık 270,50 TL", False)],
        TURKCELL_URL: [answer("paket/turkcell-x", 500, "12 ay taahhütle aylık 500TL", False)],
    }
    data.update(override)
    return data


class FakeGitHub:
    def __init__(self, issues=None, prs=None, closed_flagged=None, fail_on=()):
        self.issues = list(issues or [])
        self.prs = list(prs or [])
        self.closed_flagged = list(closed_flagged or [])
        self.fail_on = set(fail_on)  # bu adlı yöntemler hata fırlatır
        self.comments: dict[int, list[str]] = {}
        self.created_issues: list[tuple[str, str]] = []
        self.edited_issues: list[tuple[int, str]] = []
        self.closed_issues: list[tuple[int, str]] = []
        self.created_prs: list[dict] = []
        self.edited_prs: list[dict] = []

    def open_issues(self):
        return copy.deepcopy(self.issues)

    def _maybe_fail(self, name):
        if name in self.fail_on:
            raise RuntimeError(f"gh {name} başarısız")

    def pr_comments(self, number):
        return list(self.comments.get(number, []))

    def comment_pr(self, number, body):
        self._maybe_fail("comment_pr")
        self.comments.setdefault(number, []).append(body)

    def closed_false_positives(self):
        return copy.deepcopy(self.closed_flagged)

    def create_issue(self, title, body):
        self._maybe_fail("create_issue")
        self.created_issues.append((title, body))
        self.issues.append(
            {"number": 100 + len(self.issues), "title": title, "body": body, "labels": [{"name": fk.ISSUE_LABEL}]}
        )

    def close_issue(self, number, comment):
        self._maybe_fail("close_issue")
        self.closed_issues.append((number, comment))
        self.issues = [i for i in self.issues if i.get("number") != number]

    def edit_issue(self, number, body):
        self.edited_issues.append((number, body))

    def open_prs(self):
        return copy.deepcopy(self.prs)

    def find_open_pr(self, branch):
        self._maybe_fail("find_open_pr")
        return next((p for p in self.prs if p.get("headRefName") == branch), None)

    def create_pr(self, branch, title, body, labels):
        self._maybe_fail("create_pr")
        self.created_prs.append({"branch": branch, "title": title, "body": body, "labels": labels})

    def edit_pr(self, number, title, body, labels):
        self.edited_prs.append({"number": number, "title": title, "body": body, "labels": labels})


class FakeGit:
    """`reject_pushes`: ilk N publish_branch çağrısı PushRejected fırlatır;
    `on_reject` o anda çağrılır (diğer koşunun dala yazmasını taklit eder)."""

    def __init__(self, branch_files: dict[str, str] | None = None, reject_pushes: int = 0, on_reject=None):
        self.branch_files = branch_files or {}
        self.sha = "sha-1" if self.branch_files else ""
        self.fresh = False  # PR'sız dal taze mi (diğer koşu az önce push etti)
        self.fresh_checks: list[str] = []
        self.reject_pushes = reject_pushes
        self.on_reject = on_reject
        self.published: list[dict] = []
        self.rejected: list[dict] = []
        self.main_commits: list[list[str]] = []

    def remote_branch_sha(self, branch):
        return self.sha

    def branch_is_fresh_unmerged(self, sha):
        self.fresh_checks.append(sha)
        return self.fresh

    def read_branch_file(self, branch, path, sha=None):
        return self.branch_files.get(path)

    def publish_branch(self, branch, from_existing, files, message, expected_sha=""):
        item = {
            "branch": branch,
            "from_existing": from_existing,
            "files": files,
            "message": message,
            "expected_sha": expected_sha,
        }
        if self.reject_pushes:
            self.reject_pushes -= 1
            self.rejected.append(item)
            if self.on_reject:
                self.on_reject(self)
            raise fk.PushRejected("uzak dal değişti")
        self.published.append(item)

    def commit_main(self, paths, message):
        self.main_commits.append(list(paths))
        return True


def run(
    root,
    *,
    day="2026-11-17",
    gemini=None,
    page_map=None,
    gh=None,
    git=None,
    weekly=False,
    dry_run=False,
    links=None,
    now=None,
    mode=fk.MODE_ACTIONS,
    local_urls=(),
    sleep=None,
):
    page_map = pages() if page_map is None else page_map
    gh = gh or FakeGitHub()
    git = git or FakeGit()
    runner = fk.Runner(
        root,
        dt.date.fromisoformat(day),
        dry_run=dry_run,
        weekly=weekly,
        fetch=lambda url: (page_map[url], None) if page_map.get(url) else (None, "HTTP 503"),
        link_check=lambda url: (links or {}).get(url),
        gemini=gemini,
        gemini_skip_reason=None if gemini else "GEMINI_API_KEY tanımlı değil",
        gh=gh,
        git=git,
        log=lambda msg: None,
        now=now,
        mode=mode,
        local_urls=local_urls,
        sleep=sleep or (lambda s: None),
    )
    summary = runner.execute()
    return summary, gh, git


def published_catalog(git: FakeGit) -> dict:
    return json.loads(git.published[-1]["files"]["fiyatlar.json"])
