# python-crud-api — Hands-On Praktikum CI/CD

CI/CD pipeline untuk Python REST API dengan **Jenkins, GitHub, Docker, dan ngrok**.
Setiap `git push` ke branch `main` dikirim GitHub (webhook) melalui tunnel HTTPS ngrok ke Jenkins lokal. Jenkins lalu
menjalankan checkout → syntax check → unit test → build image → deploy → health check. Data pesan disimpan di Docker
named volume `production-api-data`, jadi tetap ada walaupun container diganti.

| | |
|---|---|
| Nama | Hatta Dwi Putranto |
| NIM | 101012330137 |
| Mata kuliah | Cloud Computing — Hands-On CI/CD Jenkins |

## 1. Arsitektur

```
Developer laptop
   | git push
   v
GitHub repository ---- webhook HTTPS ----> ngrok public URL
                                              |
                                              v
                                   Jenkins (container, :8080/:8090)
                                              |  Jenkinsfile (pipeline-as-code)
                                              v
                                   Docker Engine host  (/var/run/docker.sock)
                                              |
                                   production-api-container  -> Python API :5000
                                              |
                                   Named volume production-api-data (/var/lib/backend_data)
```

| Komponen | Port / lokasi | Peran |
|---|---|---|
| Jenkins UI | `localhost:8080` (di lab ini `localhost:8090`, karena 8080 dipakai aplikasi lain) | Job, credentials, build, Console Output |
| Python API | `localhost:5000` | REST API health, list, get, create, delete |
| ngrok | URL HTTPS sementara | Meneruskan webhook GitHub ke Jenkins lokal |
| Docker volume | `production-api-data` | Menyimpan `messages.json` di luar lifecycle container |

## 2. Struktur repository

| File | Fungsi |
|---|---|
| `app.py` | REST API (Python standard library) |
| `tests/test_app.py` | Test otomatis: health, validasi POST, CRUD, GET by id, filter |
| `Dockerfile` | Image Python 3.11 + Docker `HEALTHCHECK` |
| `.dockerignore` | Mengecualikan file Git/cache/test dari build context |
| `Jenkinsfile` | Pipeline 6 stage + tag commit SHA + rollback otomatis |
| `jenkins/Dockerfile` | Image Jenkins berisi Docker CLI, Python 3, dan curl |
| `docs/` | Bukti pengujian (output curl, kegagalan health check, Console Output) |

## 3. Endpoint API

| Method | Endpoint | Hasil |
|---|---|---|
| GET | `/health` | 200 `{"status": "active", ...}` |
| GET | `/messages` | 200 `{"messages": [...], "total": n}` |
| GET | `/messages?q=kata` | 200, hanya pesan yang mengandung `kata` (Tugas D) |
| GET | `/messages/{id}` | 200 pesan, 404 jika tidak ada, 400 jika id bukan angka (Tugas D) |
| POST | `/messages` body `{"message": "..."}` | 201 + `id`, `created_at`; 400 jika kosong, > 500 karakter, atau JSON tidak valid |
| DELETE | `/messages?index=X` | 200 item dihapus; 404 index tidak ada; 400 index hilang/bukan angka |

## 4. Menjalankan dan menguji secara manual

```bash
python3 -m unittest discover -s tests -v          # test otomatis tanpa Docker

docker build -t python-crud-api:manual .
docker volume create production-api-data
docker run -d --name production-api-container -p 5000:5000 \
  -v production-api-data:/var/lib/backend_data python-crud-api:manual

curl -i http://localhost:5000/health
curl -i -X POST http://localhost:5000/messages -H 'Content-Type: application/json' \
  -d '{"message":"Pesan pertama dari praktikum"}'
curl -s http://localhost:5000/messages
curl -i -X DELETE 'http://localhost:5000/messages?index=0'

docker stop production-api-container && docker rm production-api-container   # volume TIDAK dihapus
```

Output lengkapnya ada di [`docs/bukti-uji-manual-curl.txt`](docs/bukti-uji-manual-curl.txt).

## 5. Setup Jenkins

Perintah pada panduan me-mount `$(which docker)` dari host. Cara ini hanya berlaku di Linux. Di Windows/macOS
(Docker Desktop), Docker CLI dipasang langsung di image Jenkins (`jenkins/Dockerfile`):

```bash
docker build -t jenkins-docker:lts jenkins/
docker network create jenkins-net
docker volume create jenkins-data
docker run -d --name jenkins-server --network jenkins-net -u root \
  -p 8080:8080 -p 50000:50000 \
  -v jenkins-data:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --restart unless-stopped jenkins-docker:lts

docker exec jenkins-server cat /var/jenkins_home/secrets/initialAdminPassword
docker exec jenkins-server docker version        # Docker CLI dapat menjangkau daemon host
```

> Pada Linux, tambahkan `--add-host=host.docker.internal:host-gateway` agar health check di pipeline bisa menjangkau port 5000 host.

### 5.1 Fine-grained PAT (read-only)

GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token
- Token name: `jenkins-python-crud-api-readonly`, dengan expiration yang terbatas
- Repository access: **Only select repositories** → `python-crud-api`
- Repository permissions: **Contents = Read-only** (Metadata = Read-only otomatis)

### 5.2 Jenkins credential

Manage Jenkins → Credentials → System → Global → **Add Credentials**
- Kind: `Username with password`, Username: username GitHub, Password: PAT
- ID: **`github-pat-readonly`**, Description: `Read-only GitHub checkout for python-crud-api`

### 5.3 Pipeline job `python-crud-api-pipeline`

New Item → Pipeline → *Build Triggers*: **GitHub hook trigger for GITScm polling** → *Pipeline*: Pipeline script from
SCM, Git, `https://github.com/flakesss/python-crud-api.git`, Credentials `github-pat-readonly`, Branch `*/main`,
Script Path `Jenkinsfile` → Save → **Build Now** sekali.

### 5.4 ngrok dan GitHub webhook

```bash
ngrok config add-authtoken "<PASTE_NGROK_AUTHTOKEN>"
ngrok http 8080            # gunakan port Jenkins yang dipakai
```

Repository → Settings → Webhooks → Add webhook:
- Payload URL `https://<domain-ngrok>/github-webhook/`
- Content type `application/json`
- Just the push event, Active

Cek respons 200 pada **Recent Deliveries**.

## 6. Pipeline (`Jenkinsfile`)

| Stage | Isi |
|---|---|
| 1. Checkout Code | `checkout scm` memakai credential `github-pat-readonly`, lalu menyimpan commit SHA pendek |
| 2. Code Syntax Verification | `python3 -m py_compile app.py tests/test_app.py` |
| 3. Unit Test | `python3 -m unittest discover -s tests -v` |
| 4. Build Docker Image | tag `python-crud-api:<BUILD_NUMBER>`, `:<commit SHA>`, dan `:latest` |
| 5. Automated Deployment | simpan image lama → stop/rm container → `docker run` dengan volume `production-api-data` |
| 6. Health Check | tunggu Docker `HEALTHCHECK` = healthy → `curl` dari Jenkins ke port 5000 → `docker logs` |
| post failure | **rollback otomatis** ke image sebelumnya jika gagal setelah deploy |

## 7. Tugas C — Persistensi data

Buat dua pesan, jalankan ulang deployment lewat Jenkins (push/Build Now), lalu `GET /messages`. Pesan yang sama masih
ada. Buktinya ada di [`docs/bukti-persistensi.txt`](docs/bukti-persistensi.txt).

**Lifecycle container vs named volume:** container bersifat *disposable*. Setiap deploy, Jenkins menjalankan
`docker stop` + `docker rm`, dan writable layer container (semua file yang ditulis di dalamnya) ikut terhapus. Named
volume adalah objek Docker terpisah yang dikelola Docker Engine (`/var/lib/docker/volumes/production-api-data`).
Volume hanya dipasang (*mount*) ke `/var/lib/backend_data` dan tidak ikut terhapus oleh `docker rm`. Volume baru
hilang jika dihapus eksplisit dengan `docker volume rm` / `docker rm -v`. Container baru yang memasang volume yang sama
langsung membaca `messages.json` yang lama.

## 8. Tugas D — Pengembangan

1. **`GET /messages/{id}` dan filter `?q=`.** Setiap pesan kini punya `id` yang bertambah otomatis. Id lebih stabil
   daripada index, yang bergeser ketika ada pesan dihapus.
2. **Test otomatis** (`tests/test_app.py`) untuk health check, validasi POST (kosong, spasi, > 500 karakter, JSON
   rusak, bukan object), CRUD, GET by id, dan filter. Test dijalankan di stage *3. Unit Test*, jadi kode yang gagal
   tidak pernah sampai ke tahap build/deploy.
3. **Docker `HEALTHCHECK` vs health check curl Jenkins**

   | | Docker HEALTHCHECK | curl dari Jenkins |
   |---|---|---|
   | Dijalankan oleh | Docker Engine, di dalam container | Jenkins, dari luar container |
   | Kapan | Terus-menerus tiap 10 detik selama container hidup | Sekali, saat pipeline berjalan |
   | Yang diuji | Proses aplikasi merespons di `localhost:5000` container | Jalur lengkap: port mapping host `5000:5000` + aplikasi |
   | Hasil | Status `starting/healthy/unhealthy` di `docker ps` | Exit code menentukan stage hijau/merah |

   Pipeline memakai keduanya. Jenkins menunggu status `healthy` (sehingga tidak perlu `sleep 3` tebakan), lalu
   memastikan API bisa dijangkau dari luar.
4. **Tag image berbasis commit SHA.** Selain `BUILD_NUMBER`, image diberi tag SHA commit
   (`python-crud-api:3f2a9c1`), sehingga setiap image bisa dilacak ke commit yang menghasilkannya. Versi ini juga
   tampil di `/health`.
5. **Rollback.** Sebelum deploy, Jenkins menyimpan image yang sedang berjalan. Jika ada stage gagal setelah deploy
   (misalnya health check), blok `post { failure }` menjalankan ulang image sebelumnya dengan volume yang sama.
   Rollback manual:
   ```bash
   docker image ls python-crud-api                       # pilih tag build sebelumnya
   docker rm -f production-api-container
   docker run -d --name production-api-container -p 5000:5000 \
     -v production-api-data:/var/lib/backend_data --restart unless-stopped python-crud-api:<TAG_SEBELUMNYA>
   ```

## 9. Kegagalan yang ditemukan dan penyelesaiannya

**Gejala:** stage Health Check versi panduan (`curl -fsS http://localhost:5000/health`) gagal dengan
`curl: (7) Failed to connect to localhost port 5000`, padahal container API berjalan normal.

**Penyebab:** step `sh` dieksekusi di dalam container Jenkins. Di sana `localhost` adalah container Jenkins itu
sendiri, bukan host Docker tempat port 5000 di-publish.

**Solusi:** health check memanggil `http://host.docker.internal:5000/health`, yaitu alamat host dari dalam
container (Docker Desktop otomatis; Linux memakai `--add-host=host.docker.internal:host-gateway`). Selain itu,
pipeline menunggu status Docker `HEALTHCHECK` dulu agar tidak gagal karena aplikasi belum siap. Bukti:
[`docs/bukti-kegagalan-health-check.txt`](docs/bukti-kegagalan-health-check.txt).

## 10. Jawaban pertanyaan analisis

**1. Urutan peristiwa dari `git push` hingga container baru berjalan**
1. Developer menjalankan `git push` ke `main`.
2. GitHub mengirim HTTP POST (payload JSON event *push*) ke Payload URL ngrok.
3. ngrok meneruskannya ke Jenkins `/github-webhook/`.
4. Plugin GitHub mencocokkan URL repository dengan job yang mengaktifkan *GitHub hook trigger* dan menjadwalkan build.
5. Jenkins mengambil Jenkinsfile dan source dari GitHub memakai PAT.
6. Jenkins menjalankan syntax check dan unit test.
7. Jenkins memanggil `docker build` melalui Docker socket host.
8. Container lama dihentikan dan dihapus, lalu container baru dijalankan dengan volume yang sama.
9. Health check memastikan container baru *healthy* dan API merespons.

**2. Perbedaan PAT, webhook secret, dan ngrok authtoken**

| | Mengautentikasi | Arah |
|---|---|---|
| PAT | Jenkins (sebagai pengguna GitHub) saat mengakses Git/API | Jenkins → GitHub |
| Webhook secret | Payload webhook, dengan tanda tangan HMAC `X-Hub-Signature-256`, agar Jenkins yakin request benar dari GitHub | GitHub → Jenkins |
| ngrok authtoken | Agent ngrok ke akun ngrok untuk membuka tunnel | ngrok agent → ngrok cloud |

Ketiganya rahasia yang berbeda fungsi dan tidak bisa saling menggantikan.

**3. Mengapa PAT read-only cukup untuk checkout tetapi tidak untuk push?**
Checkout hanya membaca isi repository (izin *Contents: Read*). Push menulis commit/ref baru, dan GitHub menolaknya
(HTTP 403) jika token tidak punya *Contents: Read and write*. Prinsip *least privilege*: kalau token bocor, penyerang
hanya bisa membaca kode, bukan mengubahnya.

**4. Risiko memasang Docker socket host ke container Jenkins**
Akses ke `/var/run/docker.sock` setara akses root ke host. Siapa pun yang bisa menjalankan pipeline (atau menyusupkan
perintah lewat Jenkinsfile/plugin) dapat menjalankan container `--privileged`, mount `/` host, membaca secret container
lain, atau menghapus semua container/volume. Karena itu konfigurasi ini hanya untuk lab yang dipercaya. Di produksi
gunakan agent terpisah, Docker rootless, atau builder seperti Kaniko/BuildKit tanpa socket host.

**5. Mengapa URL ngrok yang berubah memutus webhook?**
GitHub menyimpan Payload URL secara statis. Pada paket gratis, domain ngrok bisa berganti saat agent dimulai ulang.
GitHub tetap mengirim ke domain lama yang sudah tidak terhubung ke tunnel mana pun, sehingga delivery gagal (404/502)
dan Jenkins tidak pernah menerima event. Solusinya: perbarui Payload URL, atau gunakan domain statis.

**6. Mengapa data di named volume bertahan setelah container dihapus?**
Lihat bagian 7. Volume dikelola Docker di luar filesystem container. `docker rm` hanya menghapus container beserta
writable layer-nya, bukan volume yang di-mount.

**7. Perbedaan CI dan CD di pipeline ini**
- **CI (Continuous Integration):** stage 1–4, yaitu checkout, syntax check, unit test, dan build image. Tujuannya
  memvalidasi setiap perubahan dan menghasilkan artefak (image ber-tag) yang siap dirilis.
- **CD (Continuous Deployment):** stage 5–6, yaitu menjalankan artefak itu ke lingkungan target secara otomatis lalu
  memverifikasinya dengan health check, tanpa langkah manual.

**8. Jika deploy sukses tetapi health check gagal?**
Tandai build gagal (merah) agar terlihat, lalu kembalikan layanan dulu: **rollback** ke image terakhir yang sehat
(pipeline ini melakukannya otomatis di `post { failure }`). Setelah itu diagnosis dengan Console Output,
`docker ps -a`, `docker logs production-api-container`, `docker inspect` (status health), dan `curl` manual. Perbaiki
kodenya dan push ulang. Untuk produksi, gunakan strategi blue-green/canary agar traffic baru dialihkan hanya setelah
health check lulus.

## 11. Troubleshooting singkat

| Gejala | Solusi |
|---|---|
| Checkout gagal (`Authentication failed`) | Cek credential `github-pat-readonly`, akses repo token, Contents: Read-only, masa berlaku |
| Webhook tidak memicu job | ngrok aktif? Payload URL berakhiran `/github-webhook/`? *GitHub hook trigger* tercentang? Lihat Recent Deliveries |
| `docker: command not found` di Jenkins | Gunakan image `jenkins/Dockerfile` (Docker CLI terpasang) |
| `port is already allocated` | `docker ps`, hentikan container konflik atau ubah `PORT_MAPPING` |
| Health check `Failed to connect to localhost` | Lihat bagian 9 (`host.docker.internal`) |
| Pesan hilang setelah redeploy | Pastikan volume dipasang ke `/var/lib/backend_data` dan tidak dihapus |

## 12. Keamanan

PAT, ngrok authtoken, dan password Jenkins tidak pernah disimpan di repository ini. Jenkinsfile hanya merujuk ID
credential `github-pat-readonly`. Jenkins tetap memakai autentikasi selama diekspos melalui ngrok.
