window.SearchErrors = Object.freeze({
  message: (detail, fallback) => detail === 'service.draining' ? '系统维护中，请稍后再试。' : fallback,
});
