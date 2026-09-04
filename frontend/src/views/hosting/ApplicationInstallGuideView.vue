<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const tab = ref<'overview' | 'python' | 'nodejs' | 'php' | 'terminal'>('overview')

function goApps() {
  void router.push('/apps')
}
</script>

<template>
  <div class="g">
    <header class="g-head">
      <button type="button" class="link" @click="goApps">← Applications</button>
      <h1>Install apps</h1>
      <p>PHP lives in your web folder (Nginx + PHP-FPM). Python and Node run as supervised apps on a private port.</p>
    </header>

    <nav class="g-tabs">
      <button type="button" :class="{ on: tab === 'overview' }" @click="tab = 'overview'">Overview</button>
      <button type="button" :class="{ on: tab === 'python' }" @click="tab = 'python'">Python</button>
      <button type="button" :class="{ on: tab === 'nodejs' }" @click="tab = 'nodejs'">Node</button>
      <button type="button" :class="{ on: tab === 'terminal' }" @click="tab = 'terminal'">Terminal</button>
      <button type="button" :class="{ on: tab === 'php' }" @click="tab = 'php'">PHP</button>
    </nav>

    <section v-if="tab === 'overview'" class="g-body">
      <ol class="steps">
        <li><b>Create</b> the app under Applications (pick framework + folder). Leave entry blank to auto-detect.</li>
        <li><b>Put code</b> there (Files, Git, SFTP, or Terminal) — or leave empty and we scaffold a starter.</li>
        <li><b>Deploy</b> installs deps, starts the process, and wires Nginx. No server admin needed.</li>
        <li><b>Optional:</b> “Point this domain at this app” so visitors hit Python/Node instead of PHP.</li>
      </ol>
      <p class="note">Projects you create under <code>apps/</code> via Terminal also appear under Active Applications after refresh — then click Deploy.</p>
    </section>

    <section v-else-if="tab === 'python'" class="g-body">
      <p>Fill the form and click Create — Deploy runs automatically (venv, gunicorn/uvicorn, process manager, proxy).</p>
      <ul class="tight">
        <li>FastAPI — leave entry blank or set <code>app.main</code> / <code>app</code></li>
        <li>Flask — <code>app</code> / <code>app</code></li>
        <li>Django — <code>config.wsgi</code> / <code>application</code></li>
      </ul>
      <p class="note">Your code must listen only via our process manager for production. Terminal is for setup and quick tests.</p>
      <button type="button" class="btn" @click="tab = 'terminal'">Terminal commands →</button>
    </section>

    <section v-else-if="tab === 'nodejs'" class="g-body">
      <p>Listen on <code>process.env.PORT</code> (we inject it). Example:</p>
      <pre>const port = process.env.PORT || 3000
app.listen(port, '127.0.0.1')</pre>
      <p class="note">Deploy runs <code>npm install</code>. Restart after code changes. Point the domain only if this app should own <code>/</code>.</p>
    </section>

    <section v-else-if="tab === 'terminal'" class="g-body">
      <p>Open <b>Terminal</b> in the panel. Set working directory to your app folder, then:</p>

      <h3>Setup (once)</h3>
      <pre>cd ~/apps/myapp          # or your app path
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt</pre>

      <h3>FastAPI</h3>
      <pre>source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
# or: gunicorn -k uvicorn.workers.UvicornWorker -b 127.0.0.1:8000 app.main:app</pre>

      <h3>Flask</h3>
      <pre>source .venv/bin/activate
export FLASK_APP=app.py
flask run --host 127.0.0.1 --port 8000
# or: gunicorn -b 127.0.0.1:8000 app:app</pre>

      <h3>Django</h3>
      <pre>source .venv/bin/activate
python manage.py migrate
gunicorn -b 127.0.0.1:8000 config.wsgi:application</pre>

      <p class="note">
        Terminal is for setup and debugging inside your home folder (timeouts apply — not for long-lived production servers).
        After you create a project under <code>apps/</code>, open Applications, refresh, and click <b>Deploy</b> so it stays running for visitors.
      </p>
      <button type="button" class="btn" @click="router.push('/terminal')">Open Terminal</button>
    </section>

    <section v-else class="g-body">
      <p>
        <b>Laravel / PHP</b> apps use a separate pipeline from Python/Node: Nginx + PHP-FPM from the project
        document root (Laravel: <code>public/</code>). Open <b>Applications → PHP &amp; Laravel</b> to list
        active apps and create new ones, or use <b>Stack</b> for one-click WordPress / Laravel on the site root.
      </p>
      <button type="button" class="btn" @click="goApps">Open Applications</button>
      <button type="button" class="btn" style="margin-left:0.5rem" @click="router.push('/stack')">Open Stack</button>
    </section>
  </div>
</template>

<style scoped>
.g {
  max-width: 40rem;
  margin: 0 auto;
  padding: 1rem 1rem 2rem;
  font-family: Figtree, ui-sans-serif, system-ui, sans-serif;
  color: #1a1f24;
}
.g-head h1 {
  font-size: 1.35rem;
  margin: 0.25rem 0 0.35rem;
}
.g-head p {
  margin: 0;
  color: #4a5560;
  font-size: 0.92rem;
  line-height: 1.45;
}
.link {
  border: 0;
  background: none;
  padding: 0;
  color: #3a4a5a;
  cursor: pointer;
  font: inherit;
  font-size: 0.875rem;
}
.g-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
  margin: 1rem 0 0.85rem;
}
.g-tabs button {
  border: 1px solid #d7dee6;
  background: #fff;
  border-radius: 999px;
  padding: 0.28rem 0.7rem;
  font: inherit;
  font-size: 0.8rem;
  cursor: pointer;
  color: #334;
}
.g-tabs button.on {
  background: #1a1f24;
  border-color: #1a1f24;
  color: #fff;
}
.g-body {
  font-size: 0.92rem;
  line-height: 1.5;
}
.g-body h3 {
  font-size: 0.85rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: #5a6570;
  margin: 1rem 0 0.35rem;
}
.steps {
  margin: 0;
  padding-left: 1.15rem;
}
.steps li + li {
  margin-top: 0.35rem;
}
.tight {
  margin: 0.35rem 0 0.75rem;
  padding-left: 1.1rem;
}
.note {
  background: #f4f6f8;
  border-radius: 8px;
  padding: 0.65rem 0.75rem;
  color: #3a4550;
  margin: 0.75rem 0 0;
}
pre {
  margin: 0.4rem 0 0.75rem;
  background: #111827;
  color: #e5e7eb;
  border-radius: 8px;
  padding: 0.7rem 0.8rem;
  overflow-x: auto;
  font-size: 0.78rem;
  line-height: 1.4;
}
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.88em;
}
.btn {
  margin-top: 0.75rem;
  border: 0;
  border-radius: 8px;
  background: #1a1f24;
  color: #fff;
  padding: 0.45rem 0.85rem;
  font: inherit;
  font-size: 0.875rem;
  cursor: pointer;
}
</style>
