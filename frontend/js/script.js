// 전역 변수
// 환경에 따라 API URL 자동 설정
function getApiUrls() {
    const isProduction = window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1';
    
    // AWS 백엔드 URL (Elastic Beanstalk 사용 시)
    // config.js 파일에서 설정하거나, window.AWS_BACKEND_URL로 설정
    // config.js 파일 예시: window.AWS_BACKEND_URL = 'https://your-eb-app.elasticbeanstalk.com';
    const AWS_BACKEND_URL = window.AWS_BACKEND_URL || null;
    
    // 프로덕션에서는 Vercel 프록시 사용 (HTTPS 지원)
    const API_BASE_URL = isProduction 
        ? `${window.location.origin}/api/proxy?path=`  // Vercel 프록시 사용
        : 'http://localhost:3000/api';     // 로컬: Node 서버
    
    const PYTHON_API_URL = isProduction 
        ? `${window.location.origin}/api/proxy?path=`  // Vercel 프록시 사용
        : 'http://localhost:5000/api';     // 로컬: Python Flask 서버
    
    return { API_BASE_URL, PYTHON_API_URL };
}

// API URL 변수 (초기값 설정)
let API_BASE_URL = getApiUrls().API_BASE_URL;
let PYTHON_API_URL = getApiUrls().PYTHON_API_URL;

// API URL 헬퍼 함수 (프록시 사용 시 경로 인코딩)
function buildApiUrl(baseUrl, path) {
    const isProduction = window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1';
    
    // 프로덕션에서 프록시 사용 시
    if (isProduction && baseUrl.includes('/api/proxy')) {
        // 경로를 URL 인코딩하여 프록시 파라미터로 전달
        const encodedPath = encodeURIComponent(path);
        // baseUrl이 이미 '?path='로 끝나는지 확인
        const separator = baseUrl.includes('?') ? '&' : '?';
        const url = `${baseUrl}${separator}path=${encodedPath}`;
        console.log('[buildApiUrl] 프록시 URL 생성:', { baseUrl, path, encodedPath, url });
        return url;
    }
    
    // 로컬 또는 직접 URL 사용 시
    const url = `${baseUrl}/${path}`.replace(/\/+/g, '/').replace(':/', '://');
    console.log('[buildApiUrl] 직접 URL 생성:', { baseUrl, path, url });
    return url;
}

// API URL을 동적으로 가져오는 함수 (config.js 로드 후 실행)
function initializeApiUrls() {
    const urls = getApiUrls();
    // 변수 업데이트
    API_BASE_URL = urls.API_BASE_URL;
    PYTHON_API_URL = urls.PYTHON_API_URL;
    console.log('API URLs 설정:', { 
        API_BASE_URL: API_BASE_URL, 
        PYTHON_API_URL: PYTHON_API_URL,
        AWS_BACKEND_URL: window.AWS_BACKEND_URL,
        isProduction: window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1'
    });
}

// 초기화 (DOMContentLoaded 또는 즉시 실행)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeApiUrls);
} else {
    // 이미 로드된 경우 즉시 실행
    initializeApiUrls();
}

// 차트 인스턴스 보관
const chartInstances = {};

// DOM 요소 변수
let chatMessages, userInput, sendButton, imageUploadInput, imageUploadButton;

// 간단한 응답 규칙
const responses = {
    '안녕': '안녕하세요!',
    '안녕하세요': '안녕하세요! 주식 정보를 검색해드립니다.',
    '반가워': '반가워요!',
    '이름': '저는 주식 정보 챗봇입니다.',
    '도움말': '종목명이나 심볼을 입력하면 주가 정보를 알려드립니다.',
    '고마워': '천만에요!',
    '감사': '별말씀을요!',
    '종료': '안녕히 가세요!',
};

const MARKET_ALIAS_MAP = {
    'nasdaq': 'NASDAQ',
    '나스닥': 'NASDAQ',
    'nyse': 'NYSE',
    '뉴욕증권거래소': 'NYSE',
    'krx': 'KRX',
    'kospi': 'KRX',
    '코스피': 'KRX',
    'kosdaq': 'KRX',
    '코스닥': 'KRX'
};

const SUPPORTED_MARKETS = new Set(['NASDAQ', 'NYSE', 'KRX']);

// 이미지 업로드 처리
async function handleImageFile(file) {
    if (!file) {
        return;
    }

    displayImagePreviewMessage(file);

    const loadingId = addLoadingMessage('이미지 분석 중...');

    try {
        const analysisResult = await requestVisionAnalysis(file);

        removeMessage(loadingId);

        if (analysisResult) {
            addVisionResultMessage(analysisResult);
        } else {
            addMessage('이미지 분석 결과를 가져오지 못했습니다.', 'bot');
        }
    } catch (error) {
        console.error('이미지 분석 오류:', error);
        removeMessage(loadingId);
        addMessage('이미지 분석 중 오류가 발생했습니다.', 'bot');
    }
}

function displayImagePreviewMessage(file) {
    const reader = new FileReader();
    reader.onload = () => {
        const img = document.createElement('img');
        img.src = reader.result;
        img.alt = file.name || '업로드한 이미지';
        img.className = 'image-preview';
        addMessage(img, 'user');
    };
    reader.readAsDataURL(file);
}

async function requestVisionAnalysis(file) {
    const formData = new FormData();
    formData.append('file', file, file.name || 'image.jpg');
    
    const isProduction = window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1';
    // FormData는 프록시를 통과할 수 없으므로, 프로덕션에서는 직접 AWS URL 사용 (CORS 허용 필요)
    const visionUrl = isProduction 
        ? 'http://kdafinal-backend-env.eba-spmee7zz.ap-northeast-2.elasticbeanstalk.com/api/vision/analyze-image'
        : buildApiUrl(PYTHON_API_URL, 'vision/analyze-image');

    const response = await fetch(visionUrl, {
        method: 'POST',
        body: formData
    });

    if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`이미지 분석 API 오류 (${response.status}): ${errorText}`);
    }

    return response.json();
}

function addVisionResultMessage(result) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message bot-message';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content stock-content';

    const container = document.createElement('div');
    container.className = 'vision-result';

    const primary = result?.primary || {};
    const fallback = result?.fallback;
    const usedFallback = Boolean(result?.used_fallback);

    const fieldsHtml = `
        <div class="vision-model">기본 분석 모델: ${primary.model || '알 수 없음'}</div>
        <div class="vision-fields">
            ${createVisionField('주요 물체', primary.object)}
            ${createVisionField('브랜드', primary.brand)}
            ${createVisionField('소유 기업', primary.company)}
            ${createVisionField('상장 시장', primary.company_market)}
            ${createVisionField('티커', primary.company_ticker)}
        </div>
    `;

    // 보강 정보 HTML 생성
    let enrichmentHtml = '';
    
    // 1. 지주회사 정보
    if (result?.holding_company) {
        const hc = result.holding_company;
        enrichmentHtml += `
            <div class="vision-enrichment-section">
                <h5>🏢 지주회사 상장 정보</h5>
                <div class="vision-fields">
                    ${createVisionField('지주회사', hc.holding_company)}
                    ${createVisionField('상장 거래소', hc.holding_market)}
                    ${createVisionField('티커', hc.holding_ticker)}
                    ${hc.holding_confidence ? `<div class="vision-field"><span class="label">신뢰도</span><span class="value">${(hc.holding_confidence * 100).toFixed(1)}%</span></div>` : ''}
                </div>
                ${hc.holding_sources && hc.holding_sources.length > 0 
                    ? `<div class="vision-sources"><strong>출처:</strong> ${hc.holding_sources.join(', ')}</div>` 
                    : ''}
            </div>
        `;
    }
    
    // 2. 밸류체인 공급사
    if (result?.value_chain && result.value_chain.length > 0) {
        enrichmentHtml += `
            <div class="vision-enrichment-section">
                <h5>🔗 주요 부품·공급사 (밸류체인)</h5>
                <div class="value-chain-list">
                    ${result.value_chain.map((vc, idx) => `
                        <div class="value-chain-item">
                            <div class="value-chain-header">
                                <strong>${idx + 1}. ${vc.component || '-'}</strong>
                                ${vc.confidence ? `<span class="confidence-badge">신뢰도: ${(vc.confidence * 100).toFixed(0)}%</span>` : ''}
                            </div>
                            <div class="vision-fields">
                                ${createVisionField('공급사', vc.supplier_company)}
                                ${createVisionField('거래소', vc.supplier_exchange)}
                                ${createVisionField('티커', vc.supplier_ticker)}
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }
    
    // 3. 관련 상장사
    if (result?.related_public_companies && result.related_public_companies.length > 0) {
        enrichmentHtml += `
            <div class="vision-enrichment-section">
                <h5>🔎 제품 관련 상장사</h5>
                <div class="related-companies-list">
                    ${result.related_public_companies.map((comp, idx) => `
                        <div class="related-company-item">
                            <strong>${idx + 1}. ${comp.company || '-'}</strong>
                            <span class="company-info">${comp.market || '-'} · ${comp.ticker || '-'}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;
    }

    container.innerHTML = `
        <h4>🧠 이미지 분석 결과</h4>
        ${fieldsHtml}
        ${
            fallback
                ? `<div class="vision-summary-block">
                        <h5>Gemini 폴백 결과 (${fallback.model || '알 수 없음'})</h5>
                        <div class="vision-fields">
                            ${createVisionField('주요 물체', fallback.object)}
                            ${createVisionField('브랜드', fallback.brand)}
                            ${createVisionField('소유 기업', fallback.company)}
                            ${createVisionField('상장 시장', fallback.company_market)}
                            ${createVisionField('티커', fallback.company_ticker)}
                        </div>
                        ${fallback.error ? `<div class="vision-fallback-note">⚠️ 폴백 오류: ${fallback.error}</div>` : ''}
                   </div>`
                : ''
        }
        ${
            usedFallback
                ? `<div class="vision-fallback-note">⚠️ 기본 분석이 실패하여 Gemini 직접 분석 결과가 사용되었습니다.</div>`
                : ''
        }
        ${enrichmentHtml}
    `;

    const stockCandidate = getVisionStockCandidate(result);

    if (stockCandidate) {
        fetchStockData(stockCandidate.searchTicker)
            .then((stockData) => {
                if (stockData) {
                    addStockMessage(stockData);
                } else {
                    const tickerLabel = `${stockCandidate.market}:${stockCandidate.ticker}`;
                    addMessage(`${tickerLabel} 주가 정보를 찾을 수 없습니다.`, 'bot');
                }
            })
            .catch((error) => {
                console.error('Vision 연동 주가 조회 오류:', error);
                addMessage('주가 정보를 가져오는 중 오류가 발생했습니다.', 'bot');
            });
    }

    contentDiv.appendChild(container);
    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function createVisionField(label, value) {
    return `
        <div class="vision-field">
            <span class="label">${label}</span>
            <span class="value">${formatVisionValue(value)}</span>
        </div>
    `;
}

function formatVisionValue(value) {
    if (value === null || value === undefined) return '-';
    const stringValue = String(value).trim();
    if (!stringValue || stringValue.toLowerCase() === 'null') return '-';
    return escapeHtml(stringValue);
}

function escapeHtml(str) {
    str = String(str);
    return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function normalizeMarketName(value) {
    if (!value && value !== 0) return null;
    const key = String(value).trim();
    if (!key) return null;
    const lookupKey = key.toLowerCase();
    if (lookupKey in MARKET_ALIAS_MAP) {
        return MARKET_ALIAS_MAP[lookupKey];
    }
    const upper = key.toUpperCase();
    return SUPPORTED_MARKETS.has(upper) ? upper : null;
}

function sanitizeTicker(value) {
    if (!value && value !== 0) return null;
    const raw = String(value).trim();
    if (!raw) return null;
    const compact = raw.replace(/\s+/g, '');
    const lowered = compact.toLowerCase();
    if (
        lowered === '비상장' ||
        lowered === 'nonlisted' ||
        lowered === 'private' ||
        lowered === 'na' ||
        lowered === 'n/a' ||
        lowered === 'null' ||
        lowered === 'none'
    ) {
        return null;
    }
    if (/^[0-9]+$/.test(compact)) {
        return compact;
    }
    return compact.toUpperCase();
}

function getVisionStockCandidate(result) {
    const sections = [];
    if (result?.primary) {
        sections.push({ ...result.primary, source: 'primary' });
    }
    if (result?.fallback) {
        sections.push({ ...result.fallback, source: 'fallback' });
    }
    // 지주회사 정보도 확인
    if (result?.holding_company) {
        const hc = result.holding_company;
        sections.push({
            company_ticker: hc.holding_ticker,
            company_market: hc.holding_market,
            company: hc.holding_company,
            source: 'holding_company'
        });
    }

    for (const section of sections) {
        const ticker = sanitizeTicker(section.company_ticker);
        const market = normalizeMarketName(section.company_market);
        if (!ticker || !market || !SUPPORTED_MARKETS.has(market)) {
            continue;
        }

        const searchTicker = (() => {
            if (market === 'KRX' && /^\d{6}$/.test(ticker)) {
                return ticker;
            }
            return ticker;
        })();

        return {
            market,
            ticker,
            searchTicker,
            source: section.source,
            company: section.company || '',
            brand: section.brand || ''
        };
    }
    return null;
}

// 사용자 메시지 전송
async function sendMessage() {
    if (!userInput) {
        console.error('userInput이 정의되지 않았습니다.');
        return;
    }
    
    const message = userInput.value.trim();
    
    if (message === '') {
        return;
    }
    
    console.log('메시지 전송:', message);
    
    // 사용자 메시지 먼저 표시
    addMessage(message, 'user');
    userInput.value = '';
    
    // 로딩 메시지 표시
    const loadingId = addLoadingMessage('검색 중...');
    
    try {
        // AI 파서 결과 적용 (쉼표로 구분된 다중 입력이 아닐 때만)
        let searchInput = message;
        let aiTicker = null;
        if (!message.includes(',')) {
            const aiParseResult = await requestStockParse(message);
            if (aiParseResult?.is_stock_query && aiParseResult.stock_name) {
                if (aiParseResult.ticker) {
                    aiTicker = aiParseResult.ticker.trim();
                }
                searchInput = (aiTicker || aiParseResult.stock_name).trim();
                console.log('[AI 파서 적용]', aiParseResult);
            }
        }
        
        // 여러 종목 입력 확인 (쉼표로 구분)
        const stocks = parseMultipleStocks(searchInput);
        
        if (stocks.length > 1) {
            // 로딩 메시지 제거
            removeMessage(loadingId);
            // 여러 종목인 경우 버튼 목록 표시
            addStockSelectionButtons(stocks);
        } else {
            // 주가 정보 검색
            const stockData = await fetchStockData(aiTicker || stocks[0] || searchInput);
            
            // 로딩 메시지 제거
            removeMessage(loadingId);
            
            if (stockData) {
                // 주가 정보 표시
                addStockMessage(stockData);
            } else {
                const botResponse = getBotResponse(message);
                addMessage(botResponse, 'bot');
            }
        }
    } catch (error) {
        removeMessage(loadingId);
        addMessage('주가 정보를 가져오는 중 오류가 발생했습니다.', 'bot');
        console.error('오류:', error);
    }
}

// 여러 종목 파싱 (쉼표로 구분)
function parseMultipleStocks(message) {
    return message.split(',').map(s => s.trim()).filter(s => s.length > 0);
}

// 주가 정보 가져오기
async function fetchStockData(query) {
    try {
        const response = await fetch(buildApiUrl(API_BASE_URL, `stock/${encodeURIComponent(query)}`));
        
        if (!response.ok) {
            if (response.status === 404) {
                return null; // 주식 정보를 찾을 수 없음
            }
            throw new Error('서버 오류');
        }
        
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('주가 정보 조회 오류:', error);
        return null;
    }
}

// AI 주식 파서 호출 (테스트용)
async function requestStockParse(input) {
    try {
        const response = await fetch(buildApiUrl(PYTHON_API_URL, 'parse-stock-query'), {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ message: input })
        });

        if (!response.ok) {
            throw new Error(`서버 오류 (${response.status})`);
        }

        const data = await response.json();
        console.log('[AI 파서 응답]', { input, data });
        return data;
    } catch (error) {
        console.error('[AI 파서 오류]', error);
        return null;
    }
}

// 차트 데이터 가져오기
async function fetchChartData(symbol, period = '1m') {
    try {
        const response = await fetch(`${buildApiUrl(API_BASE_URL, `stock/${symbol}/chart`)}?period=${period}`);
        
        if (!response.ok) {
            throw new Error('차트 데이터를 가져올 수 없습니다.');
        }
        
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('차트 데이터 조회 오류:', error);
        return null;
    }
}

// 뉴스 데이터 가져오기
async function fetchStockNews(symbol) {
    try {
        const response = await fetch(buildApiUrl(API_BASE_URL, `stock/${symbol}/news`));
        
        if (!response.ok) {
            throw new Error('뉴스를 가져올 수 없습니다.');
        }
        
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('뉴스 조회 오류:', error);
        return null;
    }
}

// 재무제표 데이터 가져오기
async function fetchStockFinancials(symbol) {
    try {
        const response = await fetch(buildApiUrl(API_BASE_URL, `stock/${symbol}/financials`));
        
        if (!response.ok) {
            throw new Error('재무제표를 가져올 수 없습니다.');
        }
        
        const data = await response.json();
        return data;
    } catch (error) {
        console.error('재무제표 조회 오류:', error);
        return null;
    }
}

// 재무제표 메시지 추가
function addFinancialMessage(companyName, symbol, financialData) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message bot-message';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content stock-content';
    
    // 고유 차트 ID 생성
    const chartId = `financial-chart-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    const segmentChartId = `segment-chart-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    
    const financialSection = document.createElement('div');
    financialSection.className = 'financial-section';
    
    // 최신 데이터 가져오기
    const latest = financialData.latest || {};
    const latestYear = latest.year || '';
    const hasSegments = financialData.segments && financialData.segments.length > 0;
    
    const chartData = financialData.chartData || [];
    const quarterData = chartData.filter(item => typeof item.year === 'string' && item.year.includes('Q'));
    const annualData = chartData.filter(item => typeof item.year === 'string' && !item.year.includes('Q'));
    const hasQuarterData = quarterData.length > 0;
    const hasAnnualData = annualData.length > 0;

    const defaultData = hasQuarterData ? quarterData : annualData;

    financialSection.innerHTML = `
        <h4 class="financial-title">📊 ${companyName} 재무제표</h4>
        ${(hasQuarterData || hasAnnualData) ? `
        <div class="financial-toggle">
            ${hasQuarterData ? `<button class="toggle-btn ${hasQuarterData ? 'active' : ''}" data-type="quarter">최근 분기</button>` : ''}
            ${hasAnnualData ? `<button class="toggle-btn ${hasQuarterData ? '' : 'active'}" data-type="annual">연간</button>` : ''}
        </div>
        ` : ''}
        <div class="financial-chart-slider">
            <div class="chart-slider-tabs">
                <button class="chart-slider-tab active" data-chart="financial">재무제표</button>
                ${hasSegments ? `<button class="chart-slider-tab" data-chart="segment">사업 부문별 매출</button>` : ''}
                <button class="chart-slider-tab" data-chart="earnings" data-symbol="${symbol}">어닝콜</button>
            </div>
            <div class="chart-slider-container">
                <div class="chart-slide active" data-chart="financial">
                    <div class="financial-chart-container">
                        <canvas id="${chartId}"></canvas>
                    </div>
                </div>
                ${hasSegments ? `
                <div class="chart-slide" data-chart="segment">
                    <div class="segment-chart-container">
                        <canvas id="${segmentChartId}"></canvas>
                    </div>
                    ${financialData.segmentDate ? `<div class="segment-date">기준일: ${financialData.segmentDate}</div>` : ''}
                </div>
                ` : ''}
                <div class="chart-slide" data-chart="earnings" id="earnings-slide-${symbol}">
                    <div class="earnings-call-container">
                        <div class="earnings-loading">로딩 중...</div>
                    </div>
                </div>
            </div>
        </div>
        <div class="financial-summary">
            <div class="financial-item">
                <span class="financial-label">매출액</span>
                <span class="financial-value">${latestYear ? formatNumberInHundredMillion(latest.revenue) : '-'}</span>
            </div>
            <div class="financial-item">
                <span class="financial-label">영업이익</span>
                <span class="financial-value">${latestYear ? formatNumberInHundredMillion(latest.operatingIncome) : '-'}</span>
            </div>
            <div class="financial-item">
                <span class="financial-label">당기순이익</span>
                <span class="financial-value">${latestYear ? formatNumberInHundredMillion(latest.netIncome) : '-'}</span>
            </div>
        </div>
        ${latestYear ? `<div class="financial-year">기준연도: ${latestYear}</div>` : ''}
        <div class="financial-question-buttons">
            <button class="financial-question-btn" data-type="revenue" data-company="${companyName}" data-symbol="${symbol}">
                <span class="question-keyword">(매출액)</span> 이 회사 앞으로도 계속 성장할까?
            </button>
            <button class="financial-question-btn" data-type="operating" data-company="${companyName}" data-symbol="${symbol}">
                <span class="question-keyword">(영업이익)</span> 이 회사는 실제로 돈을 잘 벌고 있어?
            </button>
            <button class="financial-question-btn" data-type="debt" data-company="${companyName}" data-symbol="${symbol}">
                <span class="question-keyword">(부채비율)</span> 이 회사 재무 상태 안전한 편이야?
            </button>
        </div>
    `;
    
    contentDiv.appendChild(financialSection);
    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);
    
    // 차트 렌더링
    setTimeout(() => {
        renderFinancialChart(chartId, defaultData);

        const toggleButtons = financialSection.querySelectorAll('.financial-toggle .toggle-btn');
        toggleButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                const type = btn.dataset.type;
                toggleButtons.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                const selectedData = type === 'annual' ? annualData : quarterData;
                renderFinancialChart(chartId, selectedData);
            });
        });

        // 차트 슬라이더 탭 이벤트
        const chartTabs = financialSection.querySelectorAll('.chart-slider-tab');
        const chartSlides = financialSection.querySelectorAll('.chart-slide');
        
        chartTabs.forEach(tab => {
            tab.addEventListener('click', () => {
                const chartType = tab.dataset.chart;
                
                // 탭 활성화
                chartTabs.forEach(t => t.classList.remove('active'));
                tab.classList.add('active');
                
                // 슬라이드 전환
                chartSlides.forEach(slide => {
                    if (slide.dataset.chart === chartType) {
                        slide.classList.add('active');
                    } else {
                        slide.classList.remove('active');
                    }
                });
                
                // 세그먼트 차트가 처음 보일 때 렌더링
                if (chartType === 'segment' && hasSegments) {
                    const segmentSlide = financialSection.querySelector('.chart-slide[data-chart="segment"]');
                    const segmentCanvas = segmentSlide.querySelector('canvas');
                    if (segmentCanvas && !segmentCanvas.dataset.rendered) {
                        console.log('세그먼트 데이터:', financialData.segments);
                        renderSegmentChart(segmentChartId, financialData.segments, financialData.segmentCurrency || 'USD');
                        segmentCanvas.dataset.rendered = 'true';
                    }
                }
                
                // 어닝콜이 처음 보일 때 로드
                if (chartType === 'earnings') {
                    const earningsSlide = financialSection.querySelector('.chart-slide[data-chart="earnings"]');
                    const earningsContainer = earningsSlide.querySelector('.earnings-call-container');
                    if (earningsContainer && !earningsContainer.dataset.loaded) {
                        loadEarningsCall(symbol, earningsContainer);
                        earningsContainer.dataset.loaded = 'true';
                    }
                }
            });
        });

        // 세그먼트 차트는 탭 클릭 시에만 렌더링 (지연 로딩)
        
        // 재무 질문 버튼 이벤트 리스너
        const questionButtons = financialSection.querySelectorAll('.financial-question-btn');
        questionButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                const questionType = btn.dataset.type;
                const company = btn.dataset.company;
                const symbol = btn.dataset.symbol;
                
                // 사용자 메시지 먼저 표시
                let userMessage = '';
                if (questionType === 'operating') {
                    userMessage = '영업이익';
                } else if (questionType === 'revenue') {
                    userMessage = '매출액';
                } else if (questionType === 'debt') {
                    userMessage = '부채비율';
                }
                
                if (userMessage) {
                    addMessage(userMessage, 'user');
                }
                
                if (questionType === 'operating') {
                    // 영업이익 상세 카드 표시
                    addOperatingIncomeCard(company, symbol);
                } else if (questionType === 'revenue') {
                    // 매출액 상세 카드 표시
                    addRevenueCard(company, symbol);
                } else if (questionType === 'debt') {
                    // 부채비율 상세 카드 표시
                    addDebtRatioCard(company, symbol);
                }
            });
        });
    }, 100);
    
    // 스크롤을 맨 아래로
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// 세그먼트 파이 차트 렌더링
function renderSegmentChart(canvasId, segments, currency) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !segments || segments.length === 0) {
        return;
    }
    
    // 5% 미만은 Others로 묶기
    const threshold = 5.0;
    const largeSegments = segments.filter(s => s.percentage >= threshold);
    const smallSegments = segments.filter(s => s.percentage < threshold);
    
    let chartSegments = [...largeSegments];
    if (smallSegments.length > 0) {
        const othersRevenue = smallSegments.reduce((sum, s) => sum + (s.revenue || 0), 0);
        const othersPercentage = smallSegments.reduce((sum, s) => sum + (s.percentage || 0), 0);
        if (othersRevenue > 0) {
            chartSegments.push({
                segment: 'Others',
                revenue: othersRevenue,
                percentage: othersPercentage
            });
        }
    }
    
    const labels = chartSegments.map(s => `${s.segment} (${s.percentage.toFixed(1)}%)`);
    const data = chartSegments.map(s => s.revenue);
    const colors = [
        '#667eea', '#48bb78', '#ed8936', '#f56565', '#9f7aea',
        '#38b2ac', '#f6ad55', '#fc8181', '#68d391', '#63b3ed'
    ];
    
    const ctx = canvas.getContext('2d');
    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: colors.slice(0, chartSegments.length),
                borderWidth: 2,
                borderColor: '#fff'
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    position: 'right',
                    labels: {
                        usePointStyle: true,
                        pointStyle: 'circle',
                        padding: 12,
                        font: {
                            size: 12,
                            weight: '500'
                        }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            const segment = chartSegments[context.dataIndex];
                            const currencySymbol = currency === 'KRW' ? '₩' : (currency === 'USD' ? '$' : currency);
                            const revenue = segment.revenue.toLocaleString();
                            return `${segment.segment}: ${currencySymbol}${revenue} (${segment.percentage.toFixed(1)}%)`;
                        }
                    }
                }
            }
        }
    });
}

// 재무제표 차트 렌더링
function renderFinancialChart(canvasId, chartData) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !chartData || chartData.length === 0) {
        if (chartInstances[canvasId]) {
            chartInstances[canvasId].destroy();
            delete chartInstances[canvasId];
        }
        return;
    }
    
    const ctx = canvas.getContext('2d');
    const labels = chartData.map(item => item.year);
    const revenueData = chartData.map(item => item.revenue);
    const operatingIncomeData = chartData.map(item => item.operatingIncome);
    const netIncomeData = chartData.map(item => item.netIncome);
    
    if (chartInstances[canvasId]) {
        chartInstances[canvasId].destroy();
    }

    chartInstances[canvasId] = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: '매출액',
                    data: revenueData,
                    borderColor: '#667eea',
                    backgroundColor: 'rgba(102, 126, 234, 0.1)',
                    tension: 0.4,
                    fill: false,
                    yAxisID: 'y'
                },
                {
                    label: '영업이익',
                    data: operatingIncomeData,
                    borderColor: '#48bb78',
                    backgroundColor: 'rgba(72, 187, 120, 0.1)',
                    tension: 0.4,
                    fill: false,
                    yAxisID: 'y'
                },
                {
                    label: '당기순이익',
                    data: netIncomeData,
                    borderColor: '#ed8936',
                    backgroundColor: 'rgba(237, 137, 54, 0.1)',
                    tension: 0.4,
                    fill: false,
                    yAxisID: 'y'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    position: 'bottom',
                    align: 'center',
                    labels: {
                        usePointStyle: true,
                        pointStyle: 'circle',
                        padding: 15,
                        font: {
                            size: 13,
                            weight: '500',
                            family: '-apple-system, BlinkMacSystemFont, "Segoe UI", "Roboto", "Noto Sans KR", sans-serif'
                        },
                        color: '#333',
                        boxWidth: 12,
                        boxHeight: 12
                    }
                },
                tooltip: {
                    backgroundColor: 'rgba(0, 0, 0, 0.8)',
                    padding: 12,
                    titleFont: {
                        size: 13,
                        weight: '600'
                    },
                    bodyFont: {
                        size: 12
                    },
                    borderColor: 'rgba(255, 255, 255, 0.1)',
                    borderWidth: 1,
                    cornerRadius: 8,
                    displayColors: true,
                    callbacks: {
                        label: function(context) {
                            return context.dataset.label + ': ' + formatNumberInHundredMillion(context.parsed.y);
                        }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: false,
                    grid: {
                        color: 'rgba(0, 0, 0, 0.05)',
                        drawBorder: false
                    },
                    ticks: {
                        callback: function(value) {
                            return formatNumberInHundredMillion(value);
                        },
                        font: {
                            size: 11
                        },
                        color: '#666',
                        padding: 8
                    }
                },
                x: {
                    grid: {
                        display: false
                    },
                    ticks: {
                        font: {
                            size: 11
                        },
                        color: '#666',
                        padding: 8
                    }
                }
            },
            layout: {
                padding: {
                    bottom: 10
                }
            }
        }
    });
}

// 뉴스 메시지 추가
function addNewsMessage(companyName, symbol, newsList) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message bot-message';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content stock-content';
    
    const newsSection = document.createElement('div');
    newsSection.className = 'news-section';
    newsSection.innerHTML = `
        <h4 class="news-title">📰 ${companyName} 최신 뉴스</h4>
        <div class="news-list">
            ${newsList.map((item) => `
                <div class="news-item">
                    <div class="news-header">
                        <span class="news-site">${item.site || ''}</span>
                        <span class="news-date">${item.date || ''}</span>
                    </div>
                    <div class="news-content">
                        <a href="${item.url}" target="_blank" class="news-link">
                            <strong>${item.title || '제목 없음'}</strong>
                        </a>
                        ${item.summary ? `<p class="news-summary">${item.summary}</p>` : ''}
                    </div>
                </div>
            `).join('')}
        </div>
    `;
    
    contentDiv.appendChild(newsSection);
    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);
    
    // 스크롤을 맨 아래로
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// 메시지 추가 함수
function addMessage(text, sender) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${sender}-message`;
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    
    if (typeof text === 'string') {
        contentDiv.textContent = text;
    } else {
        contentDiv.appendChild(text);
    }
    
    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);
    
    // 스크롤을 맨 아래로
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
    return messageDiv;
}

// 로딩 메시지 추가
function addLoadingMessage(text = '검색 중...') {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message bot-message';
    const messageId = `loading-${Date.now()}-${Math.random().toString(36).substr(2, 5)}`;
    messageDiv.id = messageId;
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.textContent = text;
    
    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;
    
    return messageId;
}

// 메시지 제거
function removeMessage(id) {
    const element = document.getElementById(id);
    if (element) {
        element.remove();
    }
}

// 여러 종목 선택 버튼 표시
function addStockSelectionButtons(stocks) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message bot-message';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content stock-selection-content';
    
    const title = document.createElement('div');
    title.className = 'stock-selection-title';
    title.textContent = `검색된 종목 ${stocks.length}개를 선택해주세요:`;
    
    const buttonsContainer = document.createElement('div');
    buttonsContainer.className = 'stock-selection-buttons';
    
    stocks.forEach((stock, index) => {
        const button = document.createElement('button');
        button.className = 'stock-selection-btn';
        button.textContent = `${index + 1}. ${stock}`;
        button.dataset.stock = stock;
        
        button.addEventListener('click', async () => {
            // 버튼 비활성화
            button.disabled = true;
            button.style.opacity = '0.6';
            
            // 로딩 메시지 표시
            const loadingId = addLoadingMessage();
            
            try {
                // 주가 정보 검색
                const stockData = await fetchStockData(stock);
                
                // 로딩 메시지 제거
                removeMessage(loadingId);
                
                if (stockData) {
                    // 주가 정보 표시
                    addStockMessage(stockData);
                } else {
                    addMessage(`"${stock}" 종목을 찾을 수 없습니다.`, 'bot');
                }
            } catch (error) {
                removeMessage(loadingId);
                addMessage('주가 정보를 가져오는 중 오류가 발생했습니다.', 'bot');
                console.error('오류:', error);
            } finally {
                // 버튼 다시 활성화
                button.disabled = false;
                button.style.opacity = '1';
            }
        });
        
        buttonsContainer.appendChild(button);
    });
    
    contentDiv.appendChild(title);
    contentDiv.appendChild(buttonsContainer);
    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);
    
    // 스크롤을 맨 아래로
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// 주가 정보 메시지 추가
async function addStockMessage(stockData) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message bot-message';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content stock-content';
    
    // 주가 정보 표시
    const changeColor = stockData.change >= 0 ? '#e74c3c' : '#3498db';
    const changeIcon = stockData.change >= 0 ? '▲' : '▼';
    
    // 고유 차트 ID 생성
    const chartId = `chart-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    
    const stockInfo = document.createElement('div');
    stockInfo.className = 'stock-info';
    stockInfo.innerHTML = `
        <div class="stock-header">
            <h3>${stockData.name}</h3>
            <span class="stock-symbol">${stockData.symbol}</span>
        </div>
        <div class="stock-price">
            <span class="price">${formatNumber(stockData.price)} ${stockData.currency || ''}</span>
            <span class="change" style="color: ${changeColor}">
                ${changeIcon} ${formatNumber(Math.abs(stockData.change))} 
                (${stockData.changePercent >= 0 ? '+' : ''}${stockData.changePercent.toFixed(2)}%)
            </span>
        </div>
        <div class="stock-details">
            <div class="detail-item">
                <span>시가</span>
                <span>${formatNumber(stockData.open || '-')}</span>
            </div>
            <div class="detail-item">
                <span>고가</span>
                <span>${formatNumber(stockData.high || '-')}</span>
            </div>
            <div class="detail-item">
                <span>저가</span>
                <span>${formatNumber(stockData.low || '-')}</span>
            </div>
            <div class="detail-item">
                <span>거래량</span>
                <span>${formatNumber(stockData.volume || '-')}</span>
            </div>
        </div>
        <div class="chart-container">
            <canvas id="${chartId}"></canvas>
        </div>
        <div class="stock-actions">
            <button class="action-btn financial-btn" data-symbol="${stockData.symbol}">
                📊 재무제표
            </button>
            <button class="action-btn news-btn" data-symbol="${stockData.symbol}">
                📰 뉴스
            </button>
            <button class="action-btn favorite-btn" data-symbol="${stockData.symbol}" data-company="${stockData.name}">
                ⭐ 관심종목
            </button>
        </div>
    `;
    
    contentDiv.appendChild(stockInfo);
    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);
    
    // 버튼 이벤트 리스너 추가
    const financialBtn = stockInfo.querySelector('.financial-btn');
    const newsBtn = stockInfo.querySelector('.news-btn');
    const favoriteBtn = stockInfo.querySelector('.favorite-btn');
    
    if (favoriteBtn) {
        favoriteBtn.addEventListener('click', () => {
            // 사용자 메시지 먼저 표시
            addMessage('관심종목', 'user');
            
            // TODO: 관심종목 기능 구현
            console.log('관심종목 버튼 클릭:', stockData.symbol, stockData.name);
        });
    }
    
    if (financialBtn) {
        financialBtn.addEventListener('click', async () => {
            // 사용자 메시지 먼저 표시
            addMessage('재무제표', 'user');
            
            // 버튼 비활성화
            financialBtn.disabled = true;
            financialBtn.style.opacity = '0.6';
            financialBtn.textContent = '📊 재무제표 로딩 중...';
            
            try {
                const financialData = await fetchStockFinancials(stockData.symbol);
                
                if (financialData && financialData.chartData && financialData.chartData.length > 0) {
                    addFinancialMessage(stockData.name, stockData.symbol, financialData);
                } else {
                    addMessage(`${stockData.name}의 재무제표 데이터를 찾을 수 없습니다.`, 'bot');
                }
            } catch (error) {
                console.error('재무제표 조회 오류:', error);
                addMessage('재무제표를 가져오는 중 오류가 발생했습니다.', 'bot');
            } finally {
                // 버튼 다시 활성화
                financialBtn.disabled = false;
                financialBtn.style.opacity = '1';
                financialBtn.textContent = '📊 재무제표';
            }
        });
    }
    
    if (newsBtn) {
        newsBtn.addEventListener('click', async () => {
            // 사용자 메시지 먼저 표시
            addMessage('뉴스', 'user');
            
            // 버튼 비활성화
            newsBtn.disabled = true;
            newsBtn.style.opacity = '0.6';
            newsBtn.textContent = '📰 뉴스 로딩 중...';
            
            try {
                const newsData = await fetchStockNews(stockData.symbol);
                
                if (newsData && newsData.news && newsData.news.length > 0) {
                    addNewsMessage(stockData.name, stockData.symbol, newsData.news);
                } else {
                    addMessage(`${stockData.name}에 대한 뉴스를 찾을 수 없습니다.`, 'bot');
                }
            } catch (error) {
                console.error('뉴스 조회 오류:', error);
                addMessage('뉴스를 가져오는 중 오류가 발생했습니다.', 'bot');
            } finally {
                // 버튼 다시 활성화
                newsBtn.disabled = false;
                newsBtn.style.opacity = '1';
                newsBtn.textContent = '📰 뉴스';
            }
        });
    }
    
    // 차트 로드
    setTimeout(async () => {
        const chartData = await fetchChartData(stockData.symbol, '1m');
        if (chartData && chartData.data) {
            renderChart(chartId, chartData);
        }
    }, 100);
    
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// 차트 렌더링

// 영업이익 상세 카드 추가
function addOperatingIncomeCard(companyName, symbol) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message bot-message';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content financial-detail-card';
    contentDiv.style.background = 'linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%)'; // 파란색 배경
    
    // 작은 그래프를 위한 캔버스 ID 생성
    const miniChartId = `operating-mini-chart-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    
    contentDiv.innerHTML = `
        <div class="financial-detail-header">
            <h3 class="financial-detail-title">${companyName} 영업이익</h3>
            <div class="financial-detail-mini-chart">
                <canvas id="${miniChartId}"></canvas>
            </div>
        </div>
        <div class="financial-detail-summary">
            최근 3년간 영업이익이 증가하고 있어요.
        </div>
        <div class="financial-detail-question">
            왜 증가했나요?
        </div>
        <div class="financial-detail-reasons">
            <div class="financial-detail-reason-item">• 본업에서 실제로 남는 돈이 증가하는 중</div>
            <div class="financial-detail-reason-item">• 비용 관리 개선 → 수익성 상승</div>
            <div class="financial-detail-reason-item">• 매출 증가와 함께 이익도 성장하는 구조</div>
        </div>
        <div class="financial-detail-more">
            더 자세히 보시겠어요?
        </div>
        <button class="financial-detail-btn" data-type="operating-detail" data-company="${companyName}" data-symbol="${symbol}">
            영업이익 상세 보기
        </button>
    `;
    
    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);
    
    // 작은 그래프 렌더링 (우상향 추세)
    setTimeout(() => {
        renderMiniOperatingChart(miniChartId);
    }, 100);
    
    // 상세 보기 버튼 이벤트 리스너
    const detailBtn = contentDiv.querySelector('.financial-detail-btn');
    if (detailBtn) {
        detailBtn.addEventListener('click', () => {
            console.log('영업이익 상세 보기 클릭:', companyName, symbol);
            // TODO: 상세 정보 표시
        });
    }
    
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// 영업이익 미니 차트 렌더링 (우상향 추세)
function renderMiniOperatingChart(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) {
        return;
    }
    
    const ctx = canvas.getContext('2d');
    
    // 우상향 추세 데이터 생성
    const labels = ['1년 전', '2년 전', '3년 전'];
    const data = [75, 85, 95]; // 증가 추세
    
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: '영업이익',
                data: data,
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                tension: 0.4,
                fill: true,
                pointRadius: 3,
                pointHoverRadius: 5,
                pointBackgroundColor: function(context) {
                    const index = context.dataIndex;
                    if (index === 0) return '#ef4444'; // 시작점 빨간색
                    if (index === data.length - 1) return '#3b82f6'; // 끝점 파란색
                    return '#94a3b8'; // 중간점 회색
                },
                pointBorderColor: '#ffffff',
                pointBorderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    enabled: false
                }
            },
            scales: {
                y: {
                    beginAtZero: false,
                    display: false
                },
                x: {
                    display: false
                }
            }
        }
    });
}

// 매출액 상세 카드 추가
function addRevenueCard(companyName, symbol) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message bot-message';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content financial-detail-card';
    contentDiv.style.background = 'linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%)'; // 파란색 배경
    
    // 작은 그래프를 위한 캔버스 ID 생성
    const miniChartId = `revenue-mini-chart-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
    
    contentDiv.innerHTML = `
        <div class="financial-detail-header">
            <h3 class="financial-detail-title">${companyName} 매출액</h3>
            <div class="financial-detail-mini-chart">
                <canvas id="${miniChartId}"></canvas>
            </div>
        </div>
        <div class="financial-detail-summary">
            최근 3년간 매출액이 증가하고 있어요.
        </div>
        <div class="financial-detail-question">
            왜 증가했나요?
        </div>
        <div class="financial-detail-reasons">
            <div class="financial-detail-reason-item">• 제품 판매가 꾸준히 늘고 있고</div>
            <div class="financial-detail-reason-item">• 해외 매출 비중이 커지고 있으며</div>
            <div class="financial-detail-reason-item">• 브랜드 인지도 상승이 매출을 밀어주고 있어요.</div>
        </div>
        <div class="financial-detail-more">
            더 자세히 보시겠어요?
        </div>
        <button class="financial-detail-btn" data-type="revenue-detail" data-company="${companyName}" data-symbol="${symbol}">
            매출 상세 보기
        </button>
    `;
    
    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);
    
    // 작은 그래프 렌더링 (우상향 추세)
    setTimeout(() => {
        renderMiniRevenueChart(miniChartId);
    }, 100);
    
    // 상세 보기 버튼 이벤트 리스너
    const detailBtn = contentDiv.querySelector('.financial-detail-btn');
    if (detailBtn) {
        detailBtn.addEventListener('click', () => {
            console.log('매출 상세 보기 클릭:', companyName, symbol);
            // TODO: 상세 정보 표시
        });
    }
    
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// 매출액 미니 차트 렌더링 (우상향 추세)
function renderMiniRevenueChart(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) {
        return;
    }
    
    const ctx = canvas.getContext('2d');
    
    // 우상향 추세 데이터 생성
    const labels = ['1년 전', '2년 전', '3년 전'];
    const data = [80, 90, 100]; // 증가 추세
    
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: '매출액',
                data: data,
                borderColor: '#3b82f6',
                backgroundColor: 'rgba(59, 130, 246, 0.1)',
                tension: 0.4,
                fill: true,
                pointRadius: 3,
                pointHoverRadius: 5,
                pointBackgroundColor: function(context) {
                    const index = context.dataIndex;
                    if (index === 0) return '#ef4444'; // 시작점 빨간색
                    if (index === data.length - 1) return '#3b82f6'; // 끝점 파란색
                    return '#94a3b8'; // 중간점 회색
                },
                pointBorderColor: '#ffffff',
                pointBorderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                },
                tooltip: {
                    enabled: false
                }
            },
            scales: {
                y: {
                    beginAtZero: false,
                    display: false
                },
                x: {
                    display: false
                }
            }
        }
    });
}

// 부채비율 상세 카드 추가
function addDebtRatioCard(companyName, symbol) {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message bot-message';
    
    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content financial-detail-card';
    contentDiv.style.background = 'linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%)'; // 파란색 배경
    
    contentDiv.innerHTML = `
        <div class="financial-detail-header">
            <h3 class="financial-detail-title">${companyName} 부채비율</h3>
        </div>
        <div class="financial-detail-summary">
            이 회사는 120% 수준으로 '보통' 구간에 있어요.
        </div>
        <div class="financial-detail-question">
            부채비율이 줄어든 이유는?
        </div>
        <div class="financial-detail-reasons">
            <div class="financial-detail-reason-item">• 이익이 늘면서 자본이 커졌고</div>
            <div class="financial-detail-reason-item">• 차입금 규모가 안정적으로 유지되었기 때문이에요.</div>
        </div>
        <div class="financial-detail-more">
            더 자세히 보시겠어요?
        </div>
        <button class="financial-detail-btn" data-type="debt-detail" data-company="${companyName}" data-symbol="${symbol}">
            부채비율 상세 보기
        </button>
    `;
    
    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);
    
    // 상세 보기 버튼 이벤트 리스너
    const detailBtn = contentDiv.querySelector('.financial-detail-btn');
    if (detailBtn) {
        detailBtn.addEventListener('click', () => {
            console.log('부채비율 상세 보기 클릭:', companyName, symbol);
            // TODO: 상세 정보 표시
        });
    }
    
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function renderChart(canvasId, chartData) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !chartData.data || chartData.data.length === 0) {
        return;
    }
    
    const ctx = canvas.getContext('2d');
    const labels = chartData.data.map(item => {
        const date = new Date(item.date);
        return `${date.getMonth() + 1}/${date.getDate()}`;
    });
    const prices = chartData.data.map(item => item.close);
    
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: '종가',
                data: prices,
                borderColor: '#667eea',
                backgroundColor: 'rgba(102, 126, 234, 0.1)',
                tension: 0.4,
                fill: true,
                pointRadius: 0,
                pointHoverRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: false
                }
            },
            scales: {
                y: {
                    beginAtZero: false,
                    ticks: {
                        callback: function(value) {
                            return formatNumber(value);
                        }
                    }
                },
                x: {
                    ticks: {
                        maxTicksLimit: 10
                    }
                }
            }
        }
    });
}

// 숫자 포맷팅
function formatNumber(num) {
    if (num === '-' || num === null || num === undefined) return '-';
    if (typeof num === 'string') return num;
    return num.toLocaleString('ko-KR');
}

// 억 단위로 포맷팅 (재무제표용)
function formatNumberInHundredMillion(num) {
    if (num === '-' || num === null || num === undefined) return '-';
    if (typeof num === 'string') return num;
    const inHundredMillion = num / 100000000; // 억 단위로 변환
    return inHundredMillion.toLocaleString('ko-KR', { 
        minimumFractionDigits: 0,
        maximumFractionDigits: 2
    }) + '억';
}

// 봇 응답 생성 함수
function getBotResponse(message) {
    const lowerMessage = message.toLowerCase();
    
    // 키워드 매칭
    for (const [keyword, response] of Object.entries(responses)) {
        if (lowerMessage.includes(keyword)) {
            return response;
        }
    }
    
    // 기본 응답
    return '죄송해요, 이해하지 못했어요. 주식 종목명이나 심볼을 입력해주세요.';
}

// DOM 로드 후 초기화
document.addEventListener('DOMContentLoaded', () => {
    // imageUploadInput 먼저 가져오기 (랜딩 페이지와 채팅 페이지 모두에서 사용)
    imageUploadInput = document.getElementById('imageUploadInput');
    
    // 페이지 전환 관련 요소
    const landingPage = document.getElementById('landingPage');
    const chatPage = document.getElementById('chatPage');
    const startChatButton = document.getElementById('startChatButton');
    const landingCameraFloatingButton = document.getElementById('landingCameraFloatingButton');
    const homeButton = document.getElementById('homeButton');
    
    // 시작 버튼 클릭 시 채팅 페이지로 전환
    if (startChatButton) {
        startChatButton.addEventListener('click', () => {
            if (landingPage && chatPage) {
                landingPage.style.display = 'none';
                chatPage.style.display = 'flex';
            }
        });
    }
    
    // 랜딩 페이지 카메라 플로팅 버튼 클릭 시 이미지 선택 모달 열기
    if (landingCameraFloatingButton) {
        landingCameraFloatingButton.addEventListener('click', () => {
            const landingPage = document.getElementById('landingPage');
            const chatPage = document.getElementById('chatPage');
            if (landingPage && chatPage) {
                landingPage.style.display = 'none';
                chatPage.style.display = 'flex';
                // 이미지 선택 모달 열기
                setTimeout(() => {
                    const imageSelectModal = document.getElementById('imageSelectModal');
                    if (imageSelectModal) {
                        imageSelectModal.style.display = 'flex';
                    }
                }, 100);
            }
        });
    }
    
    
    // DOM 요소 선택 (채팅 페이지)
    chatMessages = document.getElementById('chatMessages');
    userInput = document.getElementById('userInput');
    sendButton = document.getElementById('sendButton');
    imageUploadButton = document.getElementById('imageUploadButton');
    
    // 요소가 존재하는지 확인
    if (!chatMessages || !userInput || !sendButton || !imageUploadInput || !imageUploadButton) {
        console.error('필수 DOM 요소를 찾을 수 없습니다.');
        return;
    }
    
    // 이벤트 리스너 등록
    sendButton.addEventListener('click', sendMessage);

    // 이미지 선택 모달 요소
    const imageSelectModal = document.getElementById('imageSelectModal');
    const cameraButton = document.getElementById('cameraButton');
    const albumButton = document.getElementById('albumButton');
    
    // 플러스 버튼 클릭 시 모달 표시
    imageUploadButton.addEventListener('click', () => {
        if (imageSelectModal) {
            imageSelectModal.style.display = 'flex';
        }
    });
    
    // 모달 배경 클릭 시 닫기
    imageSelectModal.addEventListener('click', (e) => {
        if (e.target === imageSelectModal) {
            imageSelectModal.style.display = 'none';
        }
    });
    
    // 카메라 버튼 (빈 버튼)
    if (cameraButton) {
        cameraButton.addEventListener('click', () => {
            // TODO: 카메라 기능 구현
            console.log('카메라 버튼 클릭');
            imageSelectModal.style.display = 'none';
        });
    }
    
    // 앨범 버튼 - 기존 이미지 업로드 기능 연결
    if (albumButton) {
        albumButton.addEventListener('click', () => {
            imageSelectModal.style.display = 'none';
            imageUploadInput.click();
        });
    }

    imageUploadInput.addEventListener('change', (event) => {
        const target = event.target;
        const file = target.files && target.files[0];
        if (file) {
            // 랜딩 페이지에서 이미지 선택 시 채팅 페이지로 전환
            const landingPage = document.getElementById('landingPage');
            const chatPage = document.getElementById('chatPage');
            if (landingPage && chatPage && landingPage.style.display !== 'none') {
                landingPage.style.display = 'none';
                chatPage.style.display = 'flex';
            }
            handleImageFile(file);
        }
        target.value = '';
    });
    
    userInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.keyCode === 13) {
            e.preventDefault();
            sendMessage();
        }
    });
    
    console.log('이벤트 리스너 등록 완료');
    window.testStockParse = requestStockParse;
    
    // 모바일 키보드 대응
    let isKeyboardOpen = false;
    const chatContainer = document.querySelector('.chat-container');
    const originalHeight = window.innerHeight;

    window.addEventListener('resize', () => {
        const currentHeight = window.innerHeight;
        isKeyboardOpen = currentHeight < originalHeight * 0.75;
        
        if (isKeyboardOpen) {
            // 키보드가 열렸을 때 스크롤을 맨 아래로
            setTimeout(() => {
                if (chatMessages) {
                    chatMessages.scrollTop = chatMessages.scrollHeight;
                }
            }, 100);
        }
    });

    // 입력창 포커스 시 키보드 대응
    userInput.addEventListener('focus', () => {
        setTimeout(() => {
            if (chatMessages) {
                chatMessages.scrollTop = chatMessages.scrollHeight;
            }
        }, 300);
    });

    // 터치 이벤트 최적화
    sendButton.addEventListener('touchstart', (e) => {
        e.preventDefault();
        sendButton.style.transform = 'scale(0.95)';
    }, { passive: false });

    sendButton.addEventListener('touchend', (e) => {
        e.preventDefault();
        sendButton.style.transform = 'scale(1)';
        sendMessage();
    }, { passive: false });
    
    // 홈화면 지수 데이터 로드
    loadMarketIndices('kr');
    
    // 시가총액 상위 종목 로드
    loadTopStocksByMarketCap();
    
    // 지수 탭 클릭 이벤트
    const indexTabs = document.querySelectorAll('.index-tab');
    indexTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            indexTabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            const market = tab.dataset.market;
            loadMarketIndices(market);
        });
    });
    
    // 홈 버튼 클릭 이벤트
    if (homeButton) {
        homeButton.addEventListener('click', () => {
            if (landingPage && chatPage) {
                chatPage.style.display = 'none';
                landingPage.style.display = 'block';
                // 채팅 메시지 스크롤을 맨 위로
                if (chatMessages) {
                    chatMessages.scrollTop = 0;
                }
            }
        });
    }
});

// 지수 데이터 로드 함수
async function loadMarketIndices(market) {
    const container = document.getElementById('indexCardsContainer');
    if (!container) return;
    
    // 로딩 표시
    container.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">로딩 중...</div>';
    
    try {
        const response = await fetch(buildApiUrl(PYTHON_API_URL, `market-indices/${market}`));
        if (!response.ok) {
            throw new Error('지수 데이터를 가져올 수 없습니다.');
        }
        
        const data = await response.json();
        const indices = data.indices || [];
        
        if (indices.length === 0) {
            container.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">데이터가 없습니다.</div>';
            return;
        }
        
        // 카드 생성
        container.innerHTML = '';
        indices.forEach(index => {
            const card = createIndexCard(index);
            container.appendChild(card);
        });
    } catch (error) {
        console.error('지수 데이터 로드 오류:', error);
        container.innerHTML = '<div style="padding: 20px; text-align: center; color: #e74c3c;">데이터를 불러올 수 없습니다.</div>';
    }
}

// 지수 카드 생성 함수
function createIndexCard(index) {
    const card = document.createElement('div');
    card.className = 'index-card';
    
    const change = index.change || 0;
    const changePercent = index.changePercent || 0;
    const isPositive = change > 0;
    const isNegative = change < 0;
    const changeClass = isPositive ? 'positive' : (isNegative ? 'negative' : 'neutral');
    const changeSign = isPositive ? '+' : '';
    
    card.innerHTML = `
        <div class="index-card-name">${index.name}</div>
        <div class="index-card-value">${index.value.toLocaleString()}</div>
        <div class="index-card-change ${changeClass}">
            ${changeSign}${change.toFixed(2)}(${changeSign}${changePercent.toFixed(2)}%)
        </div>
    `;
    
    return card;
}

// 시가총액 상위 종목 로드 함수
async function loadTopStocksByMarketCap() {
    const container = document.getElementById('topStocksList');
    if (!container) return;
    
    // 로딩 표시
    container.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">로딩 중...</div>';
    
    try {
        const response = await fetch(buildApiUrl(PYTHON_API_URL, 'top-stocks-by-market-cap'));
        if (!response.ok) {
            throw new Error('시가총액 상위 종목 데이터를 가져올 수 없습니다.');
        }
        
        const data = await response.json();
        const stocks = data.stocks || [];
        
        if (stocks.length === 0) {
            container.innerHTML = '<div style="padding: 20px; text-align: center; color: #666;">데이터가 없습니다.</div>';
            return;
        }
        
        // 종목 리스트 생성
        container.innerHTML = '';
        stocks.forEach(stock => {
            const item = createTopStockItem(stock);
            container.appendChild(item);
        });
    } catch (error) {
        console.error('시가총액 상위 종목 로드 오류:', error);
        container.innerHTML = '<div style="padding: 20px; text-align: center; color: #e74c3c;">데이터를 불러올 수 없습니다.</div>';
    }
}

// 시가총액 상위 종목 아이템 생성 함수
function createTopStockItem(stock) {
    const item = document.createElement('div');
    item.className = 'top-stock-item';
    
    const change = stock.change || 0;
    const changePercent = stock.changePercent || 0;
    const isPositive = change > 0;
    const isNegative = change < 0;
    const changeClass = isPositive ? 'positive' : (isNegative ? 'negative' : 'neutral');
    const changeSign = isPositive ? '+' : '';
    
    item.innerHTML = `
        <div class="top-stock-left">
            <div class="top-stock-name">${stock.name}</div>
            <div class="top-stock-market-cap">시가총액 ${stock.marketCap.toLocaleString()}억원</div>
        </div>
        <div class="top-stock-right">
            <div class="top-stock-price">${stock.price.toLocaleString()}원</div>
            <div class="top-stock-change ${changeClass}">
                ${changeSign}${change.toLocaleString()}(${changeSign}${changePercent.toFixed(2)}%)
            </div>
        </div>
    `;
    
    // 클릭 시 해당 종목 검색
    item.addEventListener('click', () => {
        const landingPage = document.getElementById('landingPage');
        const chatPage = document.getElementById('chatPage');
        if (landingPage && chatPage) {
            landingPage.style.display = 'none';
            chatPage.style.display = 'flex';
            // 종목명으로 검색
            setTimeout(() => {
                if (userInput) {
                    userInput.value = stock.name;
                    sendMessage();
                }
            }, 100);
        }
    });
    
    return item;
}

// 어닝콜 데이터 로드 함수
async function loadEarningsCall(symbol, container) {
    if (!container) return;
    
    container.innerHTML = '<div class="earnings-loading">로딩 중...</div>';
    
    try {
        const response = await fetch(buildApiUrl(PYTHON_API_URL, `stock/${symbol}/earnings-call`));
        if (!response.ok) {
            if (response.status === 404) {
                container.innerHTML = '<div class="earnings-empty">실적발표 요약 데이터가 없습니다.</div>';
            } else {
                throw new Error('어닝콜 데이터를 가져올 수 없습니다.');
            }
            return;
        }
        
        const earningsData = await response.json();
        renderEarningsCall(earningsData, container);
    } catch (error) {
        console.error('어닝콜 로드 오류:', error);
        container.innerHTML = '<div class="earnings-error">데이터를 불러올 수 없습니다.</div>';
    }
}

// 어닝콜 렌더링 함수
function renderEarningsCall(data, container) {
    if (!data || !container) return;
    
    const dateStr = data.date ? new Date(data.date).toLocaleDateString('ko-KR') : '';
    const period = data.year && data.quarter ? `${data.year} Q${data.quarter}` : '';
    
    let html = `
        <div class="earnings-call-content">
            ${dateStr || period ? `<div class="earnings-header">
                <h5>${period || dateStr}</h5>
                ${dateStr ? `<span class="earnings-date">${dateStr}</span>` : ''}
            </div>` : ''}
    `;
    
    // 핵심 요약
    if (data.core_summary && data.core_summary.length > 0) {
        html += `
            <div class="earnings-section">
                <h6 class="earnings-section-title">핵심 요약</h6>
                <ul class="earnings-list">
                    ${data.core_summary.map(item => `<li>${item}</li>`).join('')}
                </ul>
            </div>
        `;
    }
    
    // 투자하기 전에 알아두면 좋은 포인트
    if (data.investor_points && data.investor_points.length > 0) {
        html += `
            <div class="earnings-section">
                <h6 class="earnings-section-title">투자하기 전에 알아두면 좋은 포인트</h6>
                <ul class="earnings-list">
                    ${data.investor_points.map(item => `<li>${item}</li>`).join('')}
                </ul>
            </div>
        `;
    }
    
    // 세부 섹션 요약
    if (data.section_summary) {
        html += `
            <div class="earnings-section">
                <h6 class="earnings-section-title">세부 섹션 요약</h6>
                <div class="earnings-summary-text">${data.section_summary}</div>
            </div>
        `;
    }
    
    // 가이던스
    if (data.guidance && data.guidance.length > 0) {
        html += `
            <div class="earnings-section">
                <h6 class="earnings-section-title">가이던스</h6>
                <ul class="earnings-list">
                    ${data.guidance.map(item => `<li>${item}</li>`).join('')}
                </ul>
            </div>
        `;
    }
    
    // 실적발표
    if (data.release && data.release.length > 0) {
        html += `
            <div class="earnings-section">
                <h6 class="earnings-section-title">실적발표</h6>
                <ul class="earnings-list">
                    ${data.release.map(item => `<li>${item}</li>`).join('')}
                </ul>
            </div>
        `;
    }
    
    // Q&A
    if (data.qa && data.qa.length > 0) {
        html += `
            <div class="earnings-section">
                <h6 class="earnings-section-title">Q&A</h6>
                <ul class="earnings-list">
                    ${data.qa.map(item => `<li>${item}</li>`).join('')}
                </ul>
            </div>
        `;
    }
    
    if (data.source_url) {
        html += `
            <div class="earnings-source">
                <a href="${data.source_url}" target="_blank" rel="noopener noreferrer">출처 보기</a>
            </div>
        `;
    }
    
    html += '</div>';
    container.innerHTML = html;
}

