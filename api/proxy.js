/**
 * Vercel 서버리스 함수 - AWS 백엔드 프록시
 * HTTPS(Vercel) → HTTP(AWS) 요청을 프록시하여 Mixed Content 문제 해결
 */
export const config = {
  api: {
    bodyParser: {
      sizeLimit: '10mb',
    },
  },
};

export default async function handler(req, res) {
  // OPTIONS 요청 처리 (CORS preflight)
  if (req.method === 'OPTIONS') {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    return res.status(200).end();
  }

  // AWS 백엔드 URL
  const AWS_BACKEND_URL = 'http://kdafinal-backend-env.eba-spmee7zz.ap-northeast-2.elasticbeanstalk.com';
  
  // 쿼리 파라미터에서 경로 추출
  const { path, ...queryParams } = req.query;
  
  // 경로가 없으면 에러
  if (!path || path.length === 0) {
    return res.status(400).json({ error: 'Path parameter is required' });
  }
  
  // 경로 배열을 문자열로 결합
  const apiPath = Array.isArray(path) ? path.join('/') : path;
  
  // 전체 URL 구성
  const targetUrl = `${AWS_BACKEND_URL}/api/${apiPath}`;
  
  // 쿼리 파라미터 추가
  const url = new URL(targetUrl);
  Object.keys(queryParams).forEach(key => {
    if (queryParams[key]) {
      url.searchParams.append(key, queryParams[key]);
    }
  });
  
  try {
    // 요청 헤더 준비
    const requestHeaders = {
      'User-Agent': 'Vercel-Proxy',
    };
    
    // Content-Type 헤더 복사
    const contentType = req.headers['content-type'];
    if (contentType) {
      requestHeaders['Content-Type'] = contentType;
    }
    
    // 요청 옵션 준비
    const requestOptions = {
      method: req.method,
      headers: requestHeaders,
    };
    
    // POST, PUT, PATCH 요청인 경우 body 추가
    if (req.method !== 'GET' && req.method !== 'HEAD') {
      if (req.body) {
        // multipart/form-data인 경우 특별 처리
        if (contentType && contentType.includes('multipart/form-data')) {
          // FormData는 Vercel에서 직접 처리하기 어려우므로,
          // 클라이언트에서 직접 AWS로 전송하도록 유도하는 것이 좋습니다
          // 여기서는 일단 JSON으로 변환 시도
          return res.status(400).json({ 
            error: 'Multipart form data not supported through proxy',
            message: 'Please use direct AWS endpoint for file uploads'
          });
        } else if (contentType && contentType.includes('application/json')) {
          // JSON인 경우 문자열화
          requestOptions.body = JSON.stringify(req.body);
        } else {
          // 기타 형식은 그대로 전달
          requestOptions.body = req.body;
        }
      }
    }
    
    // AWS 백엔드로 요청 전송
    const response = await fetch(url.toString(), requestOptions);
    
    // 응답 데이터 추출
    const responseContentType = response.headers.get('content-type');
    let data;
    
    if (responseContentType && responseContentType.includes('application/json')) {
      data = await response.json();
    } else {
      data = await response.text();
    }
    
    // 응답 헤더 복사
    const responseHeaders = {};
    response.headers.forEach((value, key) => {
      // CORS 헤더는 제외 (우리가 직접 설정)
      if (!key.toLowerCase().startsWith('access-control-')) {
        responseHeaders[key] = value;
      }
    });
    
    // 응답 반환
    res.status(response.status);
    
    // 헤더 설정
    Object.keys(responseHeaders).forEach(key => {
      res.setHeader(key, responseHeaders[key]);
    });
    
    // CORS 헤더 추가
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');
    
    // 응답 본문 반환
    if (responseContentType && responseContentType.includes('application/json')) {
      return res.json(data);
    } else {
      return res.send(data);
    }
    
  } catch (error) {
    console.error('Proxy error:', error);
    return res.status(500).json({ 
      error: 'Proxy error',
      message: error.message 
    });
  }
}
