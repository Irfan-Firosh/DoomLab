const $ = (selector, parent = document) => parent.querySelector(selector);
const $$ = (selector, parent = document) => [
  ...parent.querySelectorAll(selector),
];

// Each replay starts on its own and loops continuously. Clicking any video
// pauses or resumes the comparison group.
const replayGroups = new Map();
for (const video of $$("video[data-replay-group]")) {
  const name = video.dataset.replayGroup;
  if (!replayGroups.has(name)) replayGroups.set(name, []);
  replayGroups.get(name).push(video);
  video.setAttribute("aria-pressed", "false");
  video.addEventListener("playing", () =>
    video.setAttribute("aria-pressed", "true"),
  );
  video.addEventListener("pause", () =>
    video.setAttribute("aria-pressed", "false"),
  );
  video.addEventListener("click", () => toggleReplayGroup(name));
  video.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      toggleReplayGroup(name);
    }
  });
}

function toggleReplayGroup(name) {
  const group = replayGroups.get(name) ?? [];
  const shouldPlay = group.some((video) => video.paused || video.ended);
  if (shouldPlay) void playGroup(group);
  else group.forEach((video) => video.pause());
}

async function playGroup(group) {
  const results = await Promise.allSettled(group.map((video) => video.play()));
  if (results.some((result) => result.status === "rejected")) {
    group.forEach((video) => video.pause());
  }
}

for (const group of replayGroups.values()) {
  Promise.all(
    group.map(
      (video) =>
        new Promise((resolve) => {
          if (video.readyState >= 2) return resolve();
          video.addEventListener("loadeddata", resolve, { once: true });
          video.addEventListener("error", resolve, { once: true });
        }),
    ),
  ).then(() => playGroup(group));
}

const dots = $$(".seed-dot");
function showSeedTooltip(dot, pointerEvent = null) {
  const scroller = dot.closest(".plot-scroll");
  const tooltip = $(".plot-tooltip", scroller);
  const scrollBounds = scroller.getBoundingClientRect();
  const dotBounds = dot.getBoundingClientRect();
  const clientX = pointerEvent?.clientX ?? dotBounds.left + dotBounds.width / 2;
  const clientY = pointerEvent?.clientY ?? dotBounds.top + dotBounds.height / 2;
  tooltip.textContent = dot.dataset.label;
  tooltip.style.left = `${Math.max(4, clientX - scrollBounds.left + scroller.scrollLeft + 10)}px`;
  tooltip.style.top = `${Math.max(4, clientY - scrollBounds.top + scroller.scrollTop + 10)}px`;
  tooltip.hidden = false;
}
function hideSeedTooltip(chart) {
  const tooltip = $(".plot-tooltip", chart.closest(".plot-scroll"));
  if (tooltip) tooltip.hidden = true;
}
function inspectSeed(dot, pointerEvent = null) {
  dots.forEach((item) =>
    item.classList.toggle(
      "seed-active",
      item.dataset.seed === dot.dataset.seed,
    ),
  );
  $("#chart-detail").textContent = dot.dataset.label;
  showSeedTooltip(dot, pointerEvent);
}
function clearSeed() {
  dots.forEach((dot) => dot.classList.remove("seed-active"));
  $("#chart-detail").textContent = "Hover or focus a dot to inspect its seed.";
}
dots.forEach((dot) => {
  dot.addEventListener("pointerenter", (event) => inspectSeed(dot, event));
  dot.addEventListener("pointermove", (event) => showSeedTooltip(dot, event));
  dot.addEventListener("focus", () => inspectSeed(dot));
  dot.addEventListener("click", () => inspectSeed(dot));
  dot.addEventListener("blur", clearSeed);
});
$$(".distribution-svg").forEach((chart) =>
  chart.addEventListener("pointerleave", () => {
    const focused = $(".seed-dot:focus", chart);
    if (focused) inspectSeed(focused);
    else clearSeed();
    hideSeedTooltip(chart);
  }),
);

// Magic UI's theme toggle uses a circular View Transition. This static-page
// version locks the control until the transition settles, so repeated clicks
// cannot interrupt or stack animations.
const themeButton = $("#theme-toggle");
const root = document.documentElement;
function syncThemeButton() {
  const isDark = root.dataset.theme === "dark";
  themeButton.setAttribute("aria-pressed", String(isDark));
  themeButton.setAttribute(
    "aria-label",
    `Switch to ${isDark ? "light" : "dark"} theme`,
  );
  themeButton.title = `Switch to ${isDark ? "light" : "dark"} theme`;
}
syncThemeButton();
let themeTransitionPending = false;
themeButton.addEventListener("click", async () => {
  if (themeTransitionPending) return;
  themeTransitionPending = true;
  themeButton.disabled = true;
  themeButton.setAttribute("aria-busy", "true");
  const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
  const bounds = themeButton.getBoundingClientRect();
  const originX = bounds.left + bounds.width / 2;
  const originY = bounds.top + bounds.height / 2;
  const radius = Math.hypot(
    Math.max(originX, innerWidth - originX),
    Math.max(originY, innerHeight - originY),
  );
  try {
    try {
      localStorage.setItem("doomlab-theme", nextTheme);
    } catch {}
    if (
      !matchMedia("(prefers-reduced-motion: reduce)").matches &&
      document.startViewTransition
    ) {
      root.style.setProperty("--theme-reveal-x", `${originX}px`);
      root.style.setProperty("--theme-reveal-y", `${originY}px`);
      root.style.setProperty("--theme-reveal-radius", `${radius}px`);
      const transition = document.startViewTransition(() => {
        root.dataset.theme = nextTheme;
      });
      await transition.finished.catch(() => {});
    } else {
      root.dataset.theme = nextTheme;
    }
  } finally {
    syncThemeButton();
    themeButton.removeAttribute("aria-busy");
    themeButton.disabled = false;
    themeTransitionPending = false;
  }
});

$("#copy-commands").addEventListener("click", async () => {
  const button = $("#copy-commands");
  const commands = "uv run doomlab eval --split test\nuv run doomlab report";
  try {
    await navigator.clipboard.writeText(commands);
    $("#copy-status").textContent = "Commands copied.";
    button.setAttribute("aria-label", "Commands copied");
    button.textContent = "Copied";
    setTimeout(() => {
      button.setAttribute("aria-label", "Copy reproduction commands");
      button.textContent = "Copy";
      $("#copy-status").textContent = "";
    }, 3500);
  } catch {
    const selection = getSelection();
    const range = document.createRange();
    range.selectNodeContents($(".code-block code"));
    selection.removeAllRanges();
    selection.addRange(range);
    $("#copy-status").textContent = "Select and copy the highlighted commands.";
  }
});

// Left index: mark the section being read.
{
  const links = [...document.querySelectorAll(".toc a")];
  const targets = links.map((link) => document.querySelector(link.getAttribute("href"))).filter(Boolean);
  const setCurrent = () => {
    const line = window.innerHeight * 0.3;
    let current = targets[0];
    for (const target of targets) {
      if (target.getBoundingClientRect().top <= line) current = target;
    }
    for (const link of links) {
      if (link.getAttribute("href") === `#${current?.id}`) link.setAttribute("aria-current", "true");
      else link.removeAttribute("aria-current");
    }
  };
  if (targets.length) {
    let pending = false;
    addEventListener("scroll", () => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(() => {
        pending = false;
        setCurrent();
      });
    }, { passive: true });
    setCurrent();
  }
}
