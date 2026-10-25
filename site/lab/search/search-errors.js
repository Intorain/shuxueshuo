window.SearchErrors = Object.freeze({
  message: (detail, fallback) => ({
    __proto__: null,
    'service.draining': '系统维护中，请稍后再试。',
    'stage_one.disabled': '课程生成暂未开放，已生成的课程仍可学习。',
    'search.account_busy': '你已有一道题正在排队或生成，请等它处理完再试。',
    'search.queue_full': '当前生成任务较多，请稍后再试。',
    'search.daily_generation_limit': '你今天的新生成次数已用完，请明天再来。已生成的课程仍可学习。',
    'search.daily_rerun_limit': '你今天的课程重跑次数已用完，请明天再试。',
    'search.global_generation_limit': '今天的全站新生成额度已用完，请明天再来。已生成的课程仍可学习。',
    'search.global_rerun_limit': '今天的全站课程重跑额度已用完，请明天再试。',
    'search.generation_paused': '课程生成已暂停，请稍后再试。已生成的课程仍可学习。',
    'search.upload_busy': '照片识别请求较多，请等当前照片处理完再试。',
    'search.request_retired': '上次提交的记录已删除，请再次点击重试以新建记录。',
  })[detail] || fallback,
});
