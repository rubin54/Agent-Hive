"""Recorded solution for the ``minecraft-clone`` template.

Exists so the full check chain of a *demanding* task can be exercised without an API key:
package installation with selective network access, a Vite build, a preview server and a
browser check of a 3D scene including screenshots.

The code here is deliberately terse. It is not a model answer for what a model should
produce — it is the test piece against which the measurement chain itself is measured.
"""

from __future__ import annotations

from .harness.providers.mock import MockProvider, call, say

INDEX_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Voxel World</title>
    <style>
      html, body { margin: 0; height: 100%; overflow: hidden; background: #87ceeb; }
      canvas { display: block; }
      #hud { position: fixed; left: 12px; top: 12px; font: 14px sans-serif; color: #fff; }
    </style>
  </head>
  <body>
    <canvas id="game"></canvas>
    <div id="hud">WASD to move | left click to break | right click to place</div>
    <script type="module" src="/main.js"></script>
  </body>
</html>
"""

MAIN_JS = """import * as THREE from "three";

const canvas = document.getElementById("game");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(1);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x87ceeb);
scene.fog = new THREE.Fog(0x87ceeb, 20, 60);

const camera = new THREE.PerspectiveCamera(
  70,
  window.innerWidth / window.innerHeight,
  0.1,
  200,
);
camera.position.set(0, 8, 18);

scene.add(new THREE.AmbientLight(0xffffff, 0.65));
const sun = new THREE.DirectionalLight(0xffffff, 0.9);
sun.position.set(12, 26, 10);
scene.add(sun);

const CUBE = new THREE.BoxGeometry(1, 1, 1);
const MATERIALS = [0x6ab04c, 0x8d6e63, 0x9e9e9e].map(
  (color) => new THREE.MeshLambertMaterial({ color }),
);

const blocks = new Map();
const keyOf = (x, y, z) => `${x},${y},${z}`;

function addBlock(x, y, z, kind) {
  const id = keyOf(x, y, z);
  if (blocks.has(id)) return;
  const mesh = new THREE.Mesh(CUBE, MATERIALS[kind % MATERIALS.length]);
  mesh.position.set(x, y, z);
  mesh.userData.cell = { x, y, z };
  scene.add(mesh);
  blocks.set(id, mesh);
}

function removeBlock(mesh) {
  const { x, y, z } = mesh.userData.cell;
  scene.remove(mesh);
  blocks.delete(keyOf(x, y, z));
}

// Terrain from overlaid sine waves - enough structure that the scene shows visibly
// varied colour values instead of passing as an empty surface.
for (let x = -10; x <= 10; x++) {
  for (let z = -10; z <= 10; z++) {
    const height = Math.round(2 + 2 * Math.sin(x * 0.4) + 2 * Math.cos(z * 0.35));
    for (let y = 0; y <= height; y++) {
      addBlock(x, y, z, y === height ? 0 : 1);
    }
  }
}

const pressed = new Set();
window.addEventListener("keydown", (event) => pressed.add(event.code));
window.addEventListener("keyup", (event) => pressed.delete(event.code));

let yaw = 0;
let pitch = 0;
canvas.addEventListener("mousemove", (event) => {
  if (event.buttons === 0) return;
  yaw -= event.movementX * 0.003;
  pitch = Math.max(-1.2, Math.min(1.2, pitch - event.movementY * 0.003));
});

const raycaster = new THREE.Raycaster();

function pick(event) {
  const rect = canvas.getBoundingClientRect();
  const pointer = new THREE.Vector2(
    ((event.clientX - rect.left) / rect.width) * 2 - 1,
    -((event.clientY - rect.top) / rect.height) * 2 + 1,
  );
  raycaster.setFromCamera(pointer, camera);
  return raycaster.intersectObjects([...blocks.values()])[0] ?? null;
}

canvas.addEventListener("contextmenu", (event) => event.preventDefault());

canvas.addEventListener("mousedown", (event) => {
  const hit = pick(event);
  if (!hit) return;
  if (event.button === 0) {
    removeBlock(hit.object);
  } else if (event.button === 2 && hit.face) {
    const { x, y, z } = hit.object.userData.cell;
    addBlock(
      x + hit.face.normal.x,
      y + hit.face.normal.y,
      z + hit.face.normal.z,
      2,
    );
  }
});

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

const clock = new THREE.Clock();

function animate() {
  const delta = Math.min(clock.getDelta(), 0.1);
  const speed = 12 * delta;

  const forward = new THREE.Vector3(-Math.sin(yaw), 0, -Math.cos(yaw));
  const right = new THREE.Vector3(Math.cos(yaw), 0, -Math.sin(yaw));

  if (pressed.has("KeyW")) camera.position.addScaledVector(forward, speed);
  if (pressed.has("KeyS")) camera.position.addScaledVector(forward, -speed);
  if (pressed.has("KeyA")) camera.position.addScaledVector(right, -speed);
  if (pressed.has("KeyD")) camera.position.addScaledVector(right, speed);
  if (pressed.has("Space")) camera.position.y += speed;
  if (pressed.has("ShiftLeft")) camera.position.y -= speed;

  camera.rotation.set(pitch, yaw, 0, "YXZ");
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}

animate();
"""


def build_voxel_demo_provider() -> MockProvider:
    return MockProvider(
        [
            call("list_files", {"path": "."}),
            call("read_file", {"path": "package.json"}),
            call("write_file", {"path": "index.html", "content": INDEX_HTML}),
            call("write_file", {"path": "main.js", "content": MAIN_JS}),
            call("run_command", {"command": "npm install --no-fund --no-audit"}),
            call("run_command", {"command": "npm run build"}),
            say(
                "Done. index.html loads main.js as a module, the canvas carries the id "
                "'game'. The world is 21x21 columns with sine-shaped height. WASD moves the "
                "camera, left click breaks a block, right click places one. `npm run build` "
                "passes and `npm run preview` serves the built version."
            ),
        ],
        model_id="mock/voxel-world",
    )
