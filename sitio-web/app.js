/* Los enlaces incluidos en el HTML funcionan incluso sin JavaScript o conexión a la API. */
const repo = 'TheOldARK/Proyecto-Fenix';
const releaseRoot = `https://github.com/${repo}/releases/download/`;
const expected = {
  windows: /^Fenix-\d+\.\d+\.\d+[a-zA-Z0-9.-]*-windows-x64-setup\.exe$/,
  macosArm: /^Fenix-Instalador-macos-arm64\.zip$/,
  macosIntel: /^Fenix-Instalador-macos-x64\.zip$/,
  linux: /^Fenix-Instalador-linux-x64\.tar\.gz$/
};

const links = {
  windows: document.getElementById('windows-download'),
  macos: document.getElementById('macos-download'),
  linux: document.getElementById('linux-download')
};
const labels = {
  windows: document.getElementById('windows-file'),
  macos: document.getElementById('macos-file'),
  linux: document.getElementById('linux-file')
};
const macChoices = document.querySelectorAll('input[name="mac-chip"]');
const macAssets = {
  arm64: { name: 'Fenix-Instalador-macos-arm64.zip', url: `${releaseRoot}v2.1.1/Fenix-Instalador-macos-arm64.zip` },
  x64: { name: 'Fenix-Instalador-macos-x64.zip', url: `${releaseRoot}v2.1.1/Fenix-Instalador-macos-x64.zip` }
};

function setDownload(platform, asset) {
  if (!asset) return;
  links[platform].href = asset.url;
  labels[platform].textContent = asset.name;
}

function selectedMacChip() {
  return document.querySelector('input[name="mac-chip"]:checked')?.value || 'arm64';
}

function updateMac() {
  setDownload('macos', macAssets[selectedMacChip()]);
}

macChoices.forEach(choice => choice.addEventListener('change', updateMac));

const platform = (navigator.userAgentData?.platform || navigator.platform || '').toLowerCase();
const recommended = /win/.test(platform) ? 'windows' : /mac/.test(platform) ? 'macos' : /linux/.test(platform) ? 'linux' : null;
if (recommended) document.querySelector(`[data-os="${recommended}"]`)?.classList.add('recommended');

async function updateFromGitHub() {
  try {
    const response = await fetch(`https://api.github.com/repos/${repo}/releases/latest`, {
      headers: { Accept: 'application/vnd.github+json' }
    });
    if (!response.ok) return;
    const release = await response.json();
    if (!/^v\d+\.\d+\.\d+[a-zA-Z0-9.-]*$/.test(release.tag_name) || !Array.isArray(release.assets)) return;
    const assetFor = pattern => release.assets.find(asset =>
      pattern.test(asset.name) &&
      asset.browser_download_url === `${releaseRoot}${release.tag_name}/${asset.name}`
    );
    const win = assetFor(expected.windows);
    const arm = assetFor(expected.macosArm);
    const intel = assetFor(expected.macosIntel);
    const linux = assetFor(expected.linux);
    if (win) setDownload('windows', { name: win.name, url: win.browser_download_url });
    if (arm) macAssets.arm64 = { name: arm.name, url: arm.browser_download_url };
    if (intel) macAssets.x64 = { name: intel.name, url: intel.browser_download_url };
    if (linux) setDownload('linux', { name: linux.name, url: linux.browser_download_url });
    updateMac();
    if (win || arm || intel || linux) {
      document.getElementById('release-status').textContent =
        'Enlaces comprobados con GitHub. Los instaladores de macOS y Linux buscan la versión compatible más reciente al abrirse.';
    }
  } catch {
    // La página conserva los enlaces verificados incluidos en el HTML.
  }
}

updateMac();
updateFromGitHub();
