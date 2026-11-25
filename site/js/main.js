/* ============================================
   SPACE SHOOTER — Site Interactions
   ============================================ */

document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initMobileMenu();
    initScrollAnimations();
    initActiveNav();
    initShare();
});

/* --- Кнопки «Поделиться» --- */
function initShare() {
    const buttons = document.querySelectorAll('[data-share]');
    const msgEl = document.getElementById('share-msg');
    if (!buttons.length) return;

    const url = location.href.split('#')[0];
    const text = 'Space Shooter — космический шутер. Играй в браузере или скачай .exe 🚀';

    function showMsg(msg, ok = true) {
        if (!msgEl) return;
        msgEl.textContent = msg;
        msgEl.style.color = ok ? '#00cc88' : '#ff6b6b';
        msgEl.classList.add('show');
        setTimeout(() => msgEl.classList.remove('show'), 3000);
    }

    const links = {
        telegram: 'https://t.me/share/url?url=' + encodeURIComponent(url) +
                  '&text=' + encodeURIComponent(text),
        vk: 'https://vk.com/share.php?url=' + encodeURIComponent(url) +
            '&title=' + encodeURIComponent(text),
        whatsapp: 'https://wa.me/?text=' + encodeURIComponent(text + ' ' + url)
    };

    buttons.forEach(btn => {
        btn.addEventListener('click', async () => {
            const kind = btn.dataset.share;
            if (kind === 'copy') {
                try {
                    await navigator.clipboard.writeText(url);
                    showMsg('Ссылка скопирована ✓');
                } catch {
                    // Фолбэк для браузеров без Clipboard API (http, старые)
                    const ta = document.createElement('textarea');
                    ta.value = url;
                    ta.style.position = 'fixed';
                    ta.style.opacity = '0';
                    document.body.appendChild(ta);
                    ta.select();
                    try {
                        document.execCommand('copy');
                        showMsg('Ссылка скопирована ✓');
                    } catch {
                        showMsg('Не удалось скопировать — скопируй адрес из строки браузера', false);
                    }
                    document.body.removeChild(ta);
                }
                return;
            }
            const target = links[kind];
            if (target) window.open(target, '_blank', 'noopener,width=600,height=500');
        });
    });
}

/* --- Theme toggle (dark/light) --- */
function initTheme() {
    const STORAGE_KEY = 'ss_theme';
    const btn = document.getElementById('theme-toggle');
    if (!btn) return;

    function apply(theme) {
        document.documentElement.setAttribute('data-theme', theme);
        btn.textContent = theme === 'light' ? '☀️' : '🌙';
        localStorage.setItem(STORAGE_KEY, theme);
    }

    // Восстанавливаем сохранённую тему или определяем по системным настройкам
    const saved = localStorage.getItem(STORAGE_KEY);
    const prefersLight = window.matchMedia('(prefers-color-scheme: light)').matches;
    apply(saved || (prefersLight ? 'light' : 'dark'));

    btn.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme');
        apply(current === 'light' ? 'dark' : 'light');
    });
}

/* --- Mobile hamburger menu --- */
function initMobileMenu() {
    const hamburger = document.querySelector('.hamburger');
    const menu = document.querySelector('.nav-menu');
    if (!hamburger || !menu) return;

    hamburger.addEventListener('click', () => {
        hamburger.classList.toggle('active');
        menu.classList.toggle('open');
    });

    // Close menu when a link is clicked
    menu.querySelectorAll('a').forEach(link => {
        link.addEventListener('click', () => {
            hamburger.classList.remove('active');
            menu.classList.remove('open');
        });
    });
}

/* --- Fade-in animations on scroll --- */
function initScrollAnimations() {
    const targets = document.querySelectorAll(
        '.feature-card, .screenshot-item, .step, .controls-card, .requirements-card, .download-content'
    );
    if (!targets.length) return;

    targets.forEach(el => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(30px)';
        el.style.transition = 'opacity .6s ease, transform .6s ease';
    });

    const observer = new IntersectionObserver(entries => {
        entries.forEach((entry, i) => {
            if (entry.isIntersecting) {
                setTimeout(() => {
                    entry.target.style.opacity = '1';
                    entry.target.style.transform = 'translateY(0)';
                }, i * 80);
                observer.unobserve(entry.target);
            }
        });
    }, { threshold: 0.15 });

    targets.forEach(el => observer.observe(el));
}

/* --- Highlight active section in navbar --- */
function initActiveNav() {
    const sections = document.querySelectorAll('section[id]');
    const navLinks = document.querySelectorAll('.nav-menu a[href^="#"]');
    if (!sections.length || !navLinks.length) return;

    const observer = new IntersectionObserver(entries => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                navLinks.forEach(link => {
                    link.classList.toggle(
                        'active',
                        link.getAttribute('href') === '#' + entry.target.id
                    );
                });
            }
        });
    }, { rootMargin: '-40% 0px -55% 0px' });

    sections.forEach(section => observer.observe(section));
}
