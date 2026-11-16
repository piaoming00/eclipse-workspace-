/* CRESCENT corporate site — minimal JS
   1) ヘッダーのスクロール状態
   2) モバイルメニュー開閉
   3) スクロールで要素をフェードイン
   4) コピーライトの年号
*/
(function () {
  "use strict";

  const header = document.getElementById("js-header");
  const burger = document.getElementById("js-burger");
  const nav = document.getElementById("js-nav");
  const body = document.body;

  /* ---------- 1) header state ---------- */
  const onScroll = () => {
    if (!header) return;
    header.classList.toggle("is-scrolled", window.scrollY > 24);
  };
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  /* ---------- 2) mobile menu ---------- */
  const closeNav = () => {
    if (!nav || !burger) return;
    nav.classList.remove("is-open");
    burger.setAttribute("aria-expanded", "false");
    burger.setAttribute("aria-label", "メニューを開く");
    body.classList.remove("is-locked");
  };

  if (burger && nav) {
    burger.addEventListener("click", () => {
      const open = nav.classList.toggle("is-open");
      burger.setAttribute("aria-expanded", String(open));
      burger.setAttribute("aria-label", open ? "メニューを閉じる" : "メニューを開く");
      body.classList.toggle("is-locked", open);
    });

    nav.querySelectorAll("a").forEach((a) => a.addEventListener("click", closeNav));

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") closeNav();
    });

    // 画面幅が広がったらメニューを閉じる
    window.addEventListener("resize", () => {
      if (window.innerWidth > 760) closeNav();
    });
  }

  /* ---------- 3) reveal on scroll ---------- */
  const targets = document.querySelectorAll("[data-reveal]");
  if ("IntersectionObserver" in window && targets.length) {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const el = entry.target;
          // 同じブロック内で少しずつ遅らせる
          const siblings = Array.from(el.parentElement.querySelectorAll("[data-reveal]"));
          const i = Math.max(0, siblings.indexOf(el));
          el.style.transitionDelay = Math.min(i * 90, 360) + "ms";
          el.classList.add("is-in");
          io.unobserve(el);
        });
      },
      { rootMargin: "0px 0px -12% 0px", threshold: 0.12 }
    );
    targets.forEach((t) => io.observe(t));
  } else {
    targets.forEach((t) => t.classList.add("is-in"));
  }

  /* ---------- 4) year ---------- */
  const y = document.getElementById("js-year");
  if (y) y.textContent = String(new Date().getFullYear());
})();
