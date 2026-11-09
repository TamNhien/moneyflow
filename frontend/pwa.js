/* MoneyFlow v1.0.27: PWA install and opt-in generic desktop reminders. */
'use strict';
(() => {
  let installPrompt = null;
  let registrationPromise = null;
  const storage = () => { try { return window.localStorage; } catch { return null; } };
  const uid = () => Number.isSafeInteger(Number(state.user?.id)) ? Number(state.user?.id) : 0;
  const enabledKey = () => `moneyflow.notify.enabled.u${uid()}`;
  const sentKey = () => `moneyflow.notify.sent.u${uid()}`;
  const canNotify = () => ('Notification' in window) && ('serviceWorker' in navigator);
  const installed = () => window.matchMedia?.('(display-mode: standalone)')?.matches || Boolean(navigator.standalone);
  const status = () => {
    const target = document.querySelector('#pwa-status');
    if (!target) return;
    const supported = ('serviceWorker' in navigator) && window.isSecureContext;
    const permission = ('Notification' in window) ? Notification.permission : 'unsupported';
    const enabled = Boolean(uid() && storage()?.getItem(enabledKey()) === 'on' && permission === 'granted');
    const installBtn = document.querySelector('[data-action="pwa-install"]');
    const notifyBtn = document.querySelector('[data-action="pwa-notify-on"]');
    const muteBtn = document.querySelector('[data-action="pwa-notify-off"]');
    if (installBtn) { installBtn.hidden = installed(); installBtn.disabled = !supported; }
    if (notifyBtn) { notifyBtn.hidden = enabled; notifyBtn.disabled = !canNotify() || !window.isSecureContext; }
    if (muteBtn) muteBtn.hidden = !enabled;
    target.textContent = !supported ? 'Cần mở bằng HTTPS và trình duyệt hỗ trợ PWA.'
      : `${installed() ? 'Đã mở dưới dạng ứng dụng.' : 'Có thể cài từ menu Cài đặt ứng dụng của Chrome/Edge nếu không hiện lời nhắc.'} Thông báo: ${enabled?'đang bật':permission==='denied'?'đã bị trình duyệt chặn':'đang tắt'}.`;
  };
  const register = () => {
    if (!('serviceWorker' in navigator) || !window.isSecureContext) return Promise.resolve(null);
    if (!registrationPromise) registrationPromise = navigator.serviceWorker.register('/sw.js', {scope:'/',updateViaCache:'none'}).catch(error => {
      console.warn('MoneyFlow PWA registration unavailable', error); return null;
    });
    return registrationPromise;
  };
  const install = async () => {
    if (!installPrompt) {toast('Chọn Cài đặt ứng dụng trong menu Chrome/Edge hoặc Thêm vào màn hình chính trên điện thoại.');return;}
    const prompt = installPrompt;
    installPrompt = null;
    await prompt.prompt();
    await prompt.userChoice;
    status();
  };
  const enable = async () => {
    if (!state.user) return;
    if (!canNotify() || !window.isSecureContext) {toast('Trình duyệt hoặc kết nối hiện tại không hỗ trợ thông báo.',true);return;}
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {toast('Trình duyệt chưa cấp quyền thông báo cho MoneyFlow.',true);status();return;}
    const reg = await register();
    if (!reg?.showNotification) {toast('Không thể đăng ký thông báo trên trình duyệt này.',true);return;}
    storage()?.setItem(enabledKey(), 'on');
    status();toast('Đã bật thông báo nhắc lịch. Chỉ hoạt động khi MoneyFlow đang mở.');
  };
  const disable = () => {
    if (state.user) storage()?.removeItem(enabledKey());
    status();toast('Đã tắt thông báo máy tính của MoneyFlow.');
  };
  const onReminders = async (count, userId) => {
    // No details, amounts or recipient names leave the app; no notification on visible pages.
    if (!state.user || Number(userId) !== uid() || !Number.isInteger(count) || count <= 0 ||
        document.visibilityState !== 'hidden' || !canNotify() || Notification.permission !== 'granted' ||
        storage()?.getItem(enabledKey()) !== 'on') return;
    const day = new Date().toLocaleDateString('en-CA');
    if (storage()?.getItem(sentKey()) === day) return;
    const reg = await register();
    if (!reg?.showNotification) return;
    await reg.showNotification('MoneyFlow: Có lịch cần kiểm tra', {
      body:'Mở MoneyFlow để xem các khoản đến hạn.', tag:'moneyflow-reminder',
      icon:'/icon-192.png', badge:'/icon-192.png', data:{url:'/'}, silent:false
    });
    storage()?.setItem(sentKey(), day);
  };
  const handleAction = async action => {
    if (action === 'pwa-install') {await install();return true;}
    if (action === 'pwa-notify-on') {await enable();return true;}
    if (action === 'pwa-notify-off') {disable();return true;}
    return false;
  };
  window.MoneyFlowPWA = {register, status, handleAction, onReminders};
  window.addEventListener('beforeinstallprompt', event => {event.preventDefault();installPrompt=event;status();});
  window.addEventListener('appinstalled', () => {installPrompt=null;status();});
  // Only while this browser tab / installed app is open. No background service or push.
  window.setInterval?.(() => {
    if (state.user && document.visibilityState === 'hidden') refreshReminders().catch(() => {});
  }, 5*60*1000);
  register();
})();
