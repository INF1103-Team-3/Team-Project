import { refreshIcons } from './state.js?v=20261114-9';

const TYPE_STYLES = {
  info: {
    wrap: 'bg-slate-900 dark:bg-slate-800 text-white border-slate-700',
    icon: 'info',
    iconClass: 'text-sky-400',
  },
  success: {
    wrap: 'bg-emerald-950/95 text-emerald-50 border-emerald-700',
    icon: 'check-circle-2',
    iconClass: 'text-emerald-400',
  },
  warning: {
    wrap: 'bg-amber-950/95 text-amber-50 border-amber-700',
    icon: 'alert-triangle',
    iconClass: 'text-amber-400',
  },
  error: {
    wrap: 'bg-rose-950/95 text-rose-50 border-rose-700',
    icon: 'alert-circle',
    iconClass: 'text-rose-400',
  },
};

export function showToast(message, type = 'info', durationMs = 4200) {
  const container = document.getElementById('toastContainer');
  if (!container || !message) return;

  const cfg = TYPE_STYLES[type] || TYPE_STYLES.info;
  const toast = document.createElement('div');
  toast.setAttribute('role', 'status');
  toast.className = `bf-toast-enter pointer-events-auto max-w-sm w-full px-4 py-3 rounded-2xl border shadow-xl backdrop-blur-md flex items-start gap-2.5 text-xs font-medium ${cfg.wrap}`;

  const iconEl = document.createElement('i');
  iconEl.setAttribute('data-lucide', cfg.icon);
  iconEl.className = `w-4 h-4 shrink-0 mt-0.5 ${cfg.iconClass}`;

  const textEl = document.createElement('p');
  textEl.className = 'flex-1 leading-relaxed';
  textEl.textContent = String(message);

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.setAttribute('aria-label', 'Dismiss notification');
  closeBtn.className = 'text-white/60 hover:text-white transition shrink-0';
  closeBtn.innerHTML = '<i data-lucide="x" class="w-3.5 h-3.5"></i>';

  const dismiss = () => {
    toast.classList.add('opacity-0', 'transition-opacity', 'duration-150');
    setTimeout(() => toast.remove(), 160);
  };
  closeBtn.addEventListener('click', dismiss);

  toast.append(iconEl, textEl, closeBtn);
  container.appendChild(toast);
  refreshIcons(toast);

  if (durationMs > 0) {
    setTimeout(() => {
      if (toast.isConnected) dismiss();
    }, durationMs);
  }
}
