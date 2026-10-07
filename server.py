"""Single-instance job API. Only the Vairis server holds its bearer token."""
import hmac
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from contextlib import contextmanager
from portal import NeedsReview, run_portal


class Jobs:
    def __init__(self, directory, executor=run_portal):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = self.directory / "jobs.sqlite3"
        self.executor = executor
        self.lock = threading.Lock()
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, owner TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL, created REAL NOT NULL, result TEXT)")
            db.execute("UPDATE jobs SET status='interrupted',message='O servidor reiniciou. Inicie uma nova consulta.' WHERE status IN ('queued','running')")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=10)
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, owner, job_id):
        with self.connect() as db:
            r = db.execute("SELECT id,status,message,created,result FROM jobs WHERE id=? AND owner=?", (job_id, owner)).fetchone()
        return None if r is None else {"id": r[0], "status": r[1], "message": r[2], "created": r[3], "result": json.loads(r[4]) if r[4] else None}

    def latest(self, owner):
        with self.connect() as db:
            r = db.execute('SELECT id FROM jobs WHERE owner=? ORDER BY created DESC LIMIT 1', (owner,)).fetchone()
        return self.get(owner, r[0]) if r else None

    def create(self, owner, job_id):
        with self.lock:
            old = self.get(owner, job_id)
            if old:
                return old
            with self.connect() as db:
                if db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]:
                    raise NeedsReview("Já existe uma consulta em andamento. Aguarde a conclusão.")
                db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,NULL)", (job_id, owner, "queued", "Consulta aguardando execução.", time.time()))
            threading.Thread(target=self.run, args=(owner, job_id), daemon=True).start()
            return self.get(owner, job_id)

    def update(self, owner, job_id, status, message, result=None):
        with self.connect() as db:
            db.execute("UPDATE jobs SET status=?,message=?,result=? WHERE id=? AND owner=?", (status, message, json.dumps(result) if result is not None else None, job_id, owner))

    def run(self, owner, job_id):
        self.update(owner, job_id, "running", "Acessando o portal, filtrando Todos e conferindo a ordem dos eventos.")
        try:
            result = self.executor(self.directory / (job_id + ".png"))
            self.update(owner, job_id, "succeeded", result["message"], result)
        except NeedsReview as e:
            self.update(owner, job_id, "needs_review", str(e))
        except Exception:
            # Raw Playwright errors may contain portal URLs/fields; keep them out of responses and logs.
            self.update(owner, job_id, "failed", "Não foi possível concluir a consulta. Confira o acesso e a disponibilidade do portal.")


def make_handler(jobs, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send_json(self, data, status=200):
            body = json.dumps(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            return hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

        def do_GET(self):
            if self.path == "/health":
                return self.send_json({"status": "ok"})
            if not self.authorized():
                return self.send_json({"error": "Acesso não autorizado."}, 401)
            if self.path == "/status":
                return self.send_json({"ready": bool(os.getenv("EVENTOS_USERNAME") and os.getenv("EVENTOS_PASSWORD")), "stage": "eventos-list-v1"})
            if self.path == '/jobs/latest':
                owner = self.headers.get('X-Vairis-Owner', '')
                if not re.fullmatch(r'[0-9a-f]{64}', owner):
                    return self.send_json({'error': 'Não encontrado.'}, 404)
                return self.send_json({'job': jobs.latest(owner)})
            match = re.fullmatch(r"/jobs/([0-9a-f-]{36})(/image)?", self.path)
            owner = self.headers.get("X-Vairis-Owner", "")
            if not match or not re.fullmatch(r"[0-9a-f]{64}", owner):
                return self.send_json({"error": "Não encontrado."}, 404)
            job = jobs.get(owner, match[1])
            if not job:
                return self.send_json({"error": "Não encontrado."}, 404)
            if not match[2]:
                return self.send_json(job)
            image = jobs.directory / (match[1] + ".png")
            if job["status"] != "succeeded" or not image.is_file():
                return self.send_json({"error": "Imagem indisponível."}, 404)
            body = image.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if not self.authorized():
                return self.send_json({"error": "Acesso não autorizado."}, 401)
            if self.path != "/jobs":
                return self.send_json({"error": "Não encontrado."}, 404)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 1 or size > 1024:
                    raise ValueError()
                data = json.loads(self.rfile.read(size))
                owner, job_id = data.get("owner", ""), data.get("id", "")
                if not re.fullmatch(r"[0-9a-f]{64}", owner) or str(uuid.UUID(job_id)) != job_id:
                    raise ValueError()
                if not os.getenv("EVENTOS_USERNAME") or not os.getenv("EVENTOS_PASSWORD"):
                    return self.send_json({"error": "O acesso ao portal ainda precisa ser configurado."}, 409)
                return self.send_json(jobs.create(owner, job_id), 202)
            except NeedsReview as e:
                return self.send_json({"error": str(e)}, 409)
            except (ValueError, TypeError, AttributeError):
                return self.send_json({"error": "Solicitação inválida."}, 400)
            except sqlite3.IntegrityError:
                return self.send_json({'error': 'Identificador indisponível. Inicie uma nova consulta.'}, 409)
    return Handler


if __name__ == "__main__":
    token = os.getenv("ROBOT_API_TOKEN", "")
    if len(token) < 32:
        raise SystemExit("Configure ROBOT_API_TOKEN com pelo menos 32 caracteres no servidor.")
    jobs = Jobs(os.getenv("ROBOT_DATA_DIR", "/app/data"))
    ThreadingHTTPServer(("0.0.0.0", int(os.getenv("PORT", "8080"))), make_handler(jobs, token)).serve_forever()
