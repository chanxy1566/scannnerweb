// csrf_setup.js
(function() {
    // 从 meta 标签获取 CSRF token（最可靠）
    const metaTag = document.querySelector('meta[name="csrf-token"]');
    if (metaTag) {
        window.csrftoken = metaTag.getAttribute('content');
    } else {
        // 降级：尝试从 cookie 获取
        function getCookie(name) {
            const value = "; " + document.cookie;
            const parts = value.split("; " + name + "=");
            if (parts.length === 2) return parts.pop().split(";").shift();
        }
        window.csrftoken = getCookie('csrf_token') || '';
    }

    // 全局 jQuery AJAX 设置
    if (window.jQuery) {
        $(document).ajaxSend(function(event, jqxhr, settings) {
            if (!/^(GET|HEAD|OPTIONS|TRACE)$/i.test(settings.type) && !jqxhr.crossDomain) {
                jqxhr.setRequestHeader("X-CSRFToken", window.csrftoken);
            }
        });
    } else {
        console.error('jQuery 未加载，CSRF token 无法自动附加');
    }
})();