"""Respaldo en GitHub: sube lo escrito y lo restaura tras un 'reinicio' (GitHub simulado)."""
import base64
import time

from jornada40 import persistencia as pe


class _Resp:
    def __init__(self, code, data=None):
        self.status_code, self._d = code, data or {}

    def json(self):
        return self._d


def test_sube_y_restaura(tmp_path, monkeypatch):
    remoto: dict[str, tuple[str, bytes]] = {}

    def put(url, json, headers, timeout):
        nombre = url.rsplit("/", 1)[1]
        if nombre in remoto and json.get("sha") != remoto[nombre][0]:
            return _Resp(409)
        sha = f"sha{len(remoto) + 1}{time.time()}"
        remoto[nombre] = (sha, base64.b64decode(json["content"]))
        return _Resp(200, {"content": {"sha": sha}})

    def get(url, params=None, headers=None, timeout=None):
        if "/git/trees/" in url:
            return _Resp(200, {"tree": [{"path": f"data/{n}", "type": "blob", "sha": s, "url": f"blob:{n}"}
                                        for n, (s, _) in remoto.items()]})
        nombre = url.split(":", 1)[1] if url.startswith("blob:") else url.rsplit("/", 1)[1]
        if nombre not in remoto:
            return _Resp(404)
        sha, datos = remoto[nombre]
        return _Resp(200, {"sha": sha, "content": base64.b64encode(datos).decode()})

    monkeypatch.setenv("GITHUB_TOKEN_DATOS", "x")
    monkeypatch.setattr(pe.requests, "put", put)
    monkeypatch.setattr(pe.requests, "get", get)
    monkeypatch.setattr(pe, "_ESPERA_SEG", 0.05)
    pe._sha.clear()

    d1 = tmp_path / "servidor1"
    d1.mkdir()
    (d1 / "auditoria.csv").write_text("a,b\n1,2\n")
    pe.subir(d1 / "auditoria.csv")
    (d1 / "auditoria.csv").write_text("a,b\n1,2\n3,4\n")      # segunda escritura seguida
    pe.subir(d1 / "auditoria.csv")
    pe.subir(d1 / "otro.csv")                                   # no está en la lista: se ignora
    for _ in range(100):
        if "auditoria.csv" in remoto and b"3,4" in remoto["auditoria.csv"][1]:
            break
        time.sleep(0.05)
    assert remoto["auditoria.csv"][1] == b"a,b\n1,2\n3,4\n"
    assert "otro.csv" not in remoto

    d2 = tmp_path / "servidor2"          # "reinicio": disco vacío
    assert pe.restaurar(d2) == ["auditoria.csv"]
    assert (d2 / "auditoria.csv").read_text() == "a,b\n1,2\n3,4\n"


def test_sin_token_no_hace_nada(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN_DATOS", raising=False)
    assert not pe.configurado()
    assert pe.restaurar(tmp_path) == []
