/*
 * Site banner - keeps --banner-h on :root equal to the banners' real height, so the page
 * can offset itself exactly even when the banner text wraps onto more lines on phones.
 * Pairs with site-banner.css; without JS the CSS one-line estimate is used.
 */
(function () {
    var box = document.querySelector('[data-site-banners]');
    if (!box) return;
    var root = document.documentElement;

    function sync() {
        root.style.setProperty('--banner-h', Math.ceil(box.getBoundingClientRect().height) + 'px');
    }

    sync();
    if ('ResizeObserver' in window) {
        new ResizeObserver(sync).observe(box);
    } else {
        window.addEventListener('resize', sync);
    }
})();
