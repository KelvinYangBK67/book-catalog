export async function request(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = '操作失敗，請稍後再試。';
    let errorData = {};
    let validationErrors = [];
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') {
        message = body.detail;
      } else if (body.detail && typeof body.detail === 'object' && !Array.isArray(body.detail)) {
        errorData = body.detail;
        message = body.detail.message || message;
      } else if (Array.isArray(body.detail)) {
        validationErrors = body.detail;
        message = body.detail.map((item) => {
          const field = Array.isArray(item.loc)
            ? item.loc.filter((part) => part !== 'body').join(' → ') : '';
          return field ? `${field}：${item.msg}` : item.msg;
        }).join('；');
      }
    } catch (_) {
      // Non-JSON error response.
    }
    const error = new Error(message);
    error.status = response.status;
    error.validationErrors = validationErrors;
    Object.assign(error, errorData);
    throw error;
  }
  return response.json();
}

export function requestJson(url, options, payload) {
  return request(url, {
    ...options,
    headers: {'Content-Type': 'application/json', ...(options?.headers || {})},
    body: JSON.stringify(payload)
  });
}
