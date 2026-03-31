'use client';

import React from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useState, useEffect, useRef, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Input } from '@/components/ui/input';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog';
import { ArrowLeft, MessageSquare, Clock, Search, Download, BarChart3, FileText, RefreshCw, Heart, MessageCircle, TrendingUp, Calendar, Trash2, Settings, Edit, File, FileImage, FileVideo, FileAudio, Archive, ExternalLink, RotateCcw, BookOpen } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { apiClient, Group, GroupStats, Topic, FileStatus, Account, AccountSelf } from '@/lib/api';
import { toast } from 'sonner';
import SafeImage from '@/components/SafeImage';
import TaskLogViewer from '@/components/TaskLogViewer';
import { ScrollArea } from '@/components/ui/scroll-area';
import { createSafeHtmlWithHighlight, extractPlainText } from '@/lib/zsxq-content-renderer';
import DownloadSettingsDialog from '@/components/DownloadSettingsDialog';
import CrawlSettingsDialog from '@/components/CrawlSettingsDialog';
import ImageGallery from '@/components/ImageGallery';

/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-unused-vars */

// 话题详情缓存，避免重复请求
const topicDetailCache: Map<string, any> = new Map();

export default function GroupDetailPage() {
  const params = useParams();
  const router = useRouter();
  const groupId = parseInt(params.groupId as string);

  const [group, setGroup] = useState<Group | null>(null);
  const [groupStats, setGroupStats] = useState<GroupStats | null>(null);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(true);
  const [topicsLoading, setTopicsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [crawlLoading, setCrawlLoading] = useState<string | null>(null);
  const [fileLoading, setFileLoading] = useState<string | null>(null);
  const [recentTasks, setRecentTasks] = useState<any[]>([]);
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(null);
  const [activeMode, setActiveMode] = useState<'crawl' | 'download'>('crawl');
  const [activeTab, setActiveTab] = useState('topics');
  const [retryCount, setRetryCount] = useState(0);
  const [isRetrying, setIsRetrying] = useState(false);
  const [selectedCrawlOption, setSelectedCrawlOption] = useState<'scheduled' | 'latest' | 'incremental' | 'all' | 'range' | null>('all');
  const [selectedDownloadOption, setSelectedDownloadOption] = useState<'time' | 'count' | null>('time');
  // 注意：topic_id 可能超过 JS 安全整数范围，这里统一按字符串处理 ID
  const [expandedComments, setExpandedComments] = useState<Set<string>>(new Set());
  const [expandedContent, setExpandedContent] = useState<Set<string>>(new Set());
  const [groupInfo, setGroupInfo] = useState<any>(null);
  const [localFileCount, setLocalFileCount] = useState<number>(0);
  const [tags, setTags] = useState<any[]>([]);
  const [selectedTag, setSelectedTag] = useState<number | null>(null);
  const [tagsLoading, setTagsLoading] = useState(false);
  const [fetchingComments, setFetchingComments] = useState<Set<number>>(new Set());
  const [refreshingTopics, setRefreshingTopics] = useState<Set<number>>(new Set());
  const [deletingTopics, setDeletingTopics] = useState<Set<number>>(new Set());
  const [cacheInfo, setCacheInfo] = useState<any>(null);
  const [clearingCache, setClearingCache] = useState(false);
  const [fileStatuses, setFileStatuses] = useState<Map<number, FileStatus>>(new Map());
  const [downloadingFiles, setDownloadingFiles] = useState<Set<number>>(new Set());

  // 账号相关
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [groupAccount, setGroupAccount] = useState<Account | null>(null);
  const [selectedAccountId, setSelectedAccountId] = useState<string>('');
  const [assigningAccount, setAssigningAccount] = useState<boolean>(false);
  const [accountSelf, setAccountSelf] = useState<AccountSelf | null>(null);
  const [loadingAccountSelf, setLoadingAccountSelf] = useState<boolean>(false);
  const [refreshingAccountSelf, setRefreshingAccountSelf] = useState<boolean>(false);

  // 专栏相关
  const [hasColumns, setHasColumns] = useState<boolean>(false);
  const [columnsTitle, setColumnsTitle] = useState<string | null>(null);






  // 话题详情缓存：key 使用字符串形式的 topic_id，避免大整数精度问题
  const [topicDetails, setTopicDetails] = useState<Map<string, any>>(new Map());
  const inFlightRef = useRef<Map<string, Promise<any>>>(new Map());
  const scrollAreaRef = useRef<HTMLDivElement>(null);



  // 估算评论高度的函数
  const estimateCommentHeight = (comment: any): number => {
    const baseHeight = 40; // 头像和用户名行的基础高度
    const textContent = extractPlainText(comment.text);
    const lineCount = Math.max(1, textContent.split('\n').length);
    const textHeight = lineCount * 16; // 每行大约16px
    const imageHeight = comment.images && comment.images.length > 0 ? 72 : 0; // 图片高度64px + margin 8px
    const padding = 16; // 内边距

    return baseHeight + textHeight + imageHeight + padding;
  };

  // 计算在指定高度内能完全显示的评论数量
  const calculateVisibleComments = (comments: any[], maxHeight: number = 180): number => {
    let totalHeight = 0;
    let visibleCount = 0;

    for (let i = 0; i < comments.length; i++) {
      const commentHeight = estimateCommentHeight(comments[i]);
      if (totalHeight + commentHeight <= maxHeight) {
        totalHeight += commentHeight;
        visibleCount++;
      } else {
        break;
      }
    }

    // 确保至少显示3条评论，除非总评论数少于3条
    const minComments = Math.min(3, comments.length);
    visibleCount = Math.max(minComments, visibleCount);

    return visibleCount;
  };

  // 下载间隔控制配置
  const [downloadInterval, setDownloadInterval] = useState<number>(1.0);
  const [longSleepInterval, setLongSleepInterval] = useState<number>(60.0);
  const [filesPerBatch, setFilesPerBatch] = useState<number>(10);
  const [showSettingsDialog, setShowSettingsDialog] = useState<boolean>(false);

  // 随机间隔范围设置
  const [downloadIntervalMin, setDownloadIntervalMin] = useState<number>(15);
  const [downloadIntervalMax, setDownloadIntervalMax] = useState<number>(30);
  const [longSleepIntervalMin, setLongSleepIntervalMin] = useState<number>(30);
  const [longSleepIntervalMax, setLongSleepIntervalMax] = useState<number>(60);
  const [useRandomInterval, setUseRandomInterval] = useState<boolean>(true);

  // 话题爬取设置状态
  const [crawlSettingsOpen, setCrawlSettingsOpen] = useState(false);
  const [crawlInterval, setCrawlInterval] = useState(3.5);
  const [crawlLongSleepInterval, setCrawlLongSleepInterval] = useState(240);
  const [crawlPagesPerBatch, setCrawlPagesPerBatch] = useState(15);
  const [crawlIntervalMin, setCrawlIntervalMin] = useState<number>(2);
  const [crawlIntervalMax, setCrawlIntervalMax] = useState<number>(5);
  const [crawlLongSleepIntervalMin, setCrawlLongSleepIntervalMin] = useState<number>(180);
  const [crawlLongSleepIntervalMax, setCrawlLongSleepIntervalMax] = useState<number>(300);
  // 时间区间采集（最近N天 或 自定义日期）
  const [quickLastDays, setQuickLastDays] = useState<number>(30);
  const [rangeStartDate, setRangeStartDate] = useState<string>('');
  const [rangeEndDate, setRangeEndDate] = useState<string>('');
  const [latestDialogOpen, setLatestDialogOpen] = useState<boolean>(false);
  
  // 定时获取相关状态
  const [scheduledRunning, setScheduledRunning] = useState<boolean>(false);
  const [scheduleIntervalMinutes, setScheduleIntervalMinutes] = useState<number>(5); // 默认 5 分钟
  const [scheduledDialogOpen, setScheduledDialogOpen] = useState<boolean>(false); // 定时获取弹窗状态

  // 单个话题采集状态
  const [singleTopicId, setSingleTopicId] = useState<string>('');
  const [fetchingSingle, setFetchingSingle] = useState<boolean>(false);

  useEffect(() => {
    loadGroupDetail();
    loadGroupStats();
    loadTopics();
    loadRecentTasks();
    loadGroupInfo();
    loadLocalFileCount();
    loadTags();
    loadCacheInfo();
    loadGroupAccount();
    loadAccounts();
    loadGroupAccountSelf();
    loadColumnsSummary();
  }, [groupId]);

  // 检查定时任务状态的函数
  const checkScheduledStatus = useCallback(async () => {
    try {
      // 调用API获取定时任务状态
      const status: any = await apiClient.getScheduledCrawlStatus(groupId);
      
      // 更新定时任务运行状态
      // status.running 如果为 true，说明定时任务正在运行
      setScheduledRunning(Boolean(status && status.running));
      
      console.log('[定时任务状态] 群组', groupId, '定时任务状态:', status);
    } catch (e) {
      console.error('获取定时任务状态失败:', e);
      // 如果API调用失败，默认设为未运行
      setScheduledRunning(false);
    }
  }, [groupId]);

  // 检查定时任务状态
  useEffect(() => {
    checkScheduledStatus();
  }, [checkScheduledStatus]);

  useEffect(() => {
    loadTopics();
  }, [currentPage, searchTerm, selectedTag]);

  // 批量预取当前页话题详情，带去重
  useEffect(() => {
    if (!topics || topics.length === 0) return;
    topics.forEach((t: any) => {
      // 直接使用后端返回的 topic_id 字符串，避免 Number 精度丢失
      const tid = String((t as any)?.topic_id || '');
      if (!tid) return;
      if (topicDetails.has(tid)) return;
      const key = `${groupId}-${tid}`;
      if (inFlightRef.current.get(key)) return;

      const p = apiClient.getTopicDetail(tid, groupId)
        .then((detail) => {
          setTopicDetails(prev => {
            const next = new Map(prev);
            next.set(tid, detail);
            return next;
          });
        })
        .catch((err) => {
          console.error('预取话题详情失败:', err);
        })
        .finally(() => {
          inFlightRef.current.delete(key);
        });

      inFlightRef.current.set(key, p);
    });
  }, [topics, groupId]);





  const loadGroupDetail = async (currentRetryCount = 0) => {
    try {
      if (currentRetryCount === 0) {
        setLoading(true);
        setError(null);
        setRetryCount(0);
        setIsRetrying(false);
      } else {
        setIsRetrying(true);
        setRetryCount(currentRetryCount);
      }

      // 获取群组列表，然后找到对应的群组
      const data = await apiClient.getGroups();

      // 检查是否获取到有效数据
      if (!data || !data.groups || data.groups.length === 0) {
        throw new Error('API返回空数据，可能是反爬虫机制');
      }

      const foundGroup = data.groups.find(g => g.group_id === groupId);

      if (foundGroup) {
        setGroup(foundGroup);
        setError(null);
        setRetryCount(0);
        setIsRetrying(false);
        setLoading(false);
      } else {
        setError('未找到指定的群组');
        setIsRetrying(false);
        setLoading(false);
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : '加载群组详情失败';

      // 如果是API保护机制导致的错误，持续重试
      if (errorMessage.includes('未知错误') || errorMessage.includes('空数据') || errorMessage.includes('反爬虫')) {
        const nextRetryCount = currentRetryCount + 1;
        const delay = Math.min(1000 + (nextRetryCount * 500), 5000); // 递增延迟，最大5秒



        setTimeout(() => {
          loadGroupDetail(nextRetryCount);
        }, delay);
        return;
      }

      // 其他错误，停止重试
      setError(errorMessage);
      setIsRetrying(false);
      setLoading(false);
    }
  };

  const loadGroupStats = async () => {
    try {
      const stats = await apiClient.getGroupStats(groupId);
      setGroupStats(stats);
    } catch (err) {
      console.error('加载群组统计失败:', err);
    }
  };

  const loadTopics = async (currentRetryCount = 0) => {
    try {
      if (currentRetryCount === 0) {
        setTopicsLoading(true);
      }

      let data;
      if (selectedTag) {
        // 如果选择了标签，使用标签过滤API
        data = await apiClient.getTagTopics(groupId, selectedTag, currentPage, 20);
      } else {
        // 否则使用原有的API
        data = await apiClient.getGroupTopics(groupId, currentPage, 20, searchTerm || undefined);
      }

       // 检查是否获取到有效数据
      if (!data || !data.data) {
        throw new Error('API返回空数据，可能是反爬虫机制');
      }

      // 🧪 调试输出：loadTopics 收到的数据
      try {
        const offerTopic = (data.data || []).find((t: any) =>
          typeof t.title === 'string' && t.title.startsWith('Offer选择')
        );
        if (offerTopic) {
          console.log('[GroupDetailPage.loadTopics] Offer topic from API client:', {
            topic_id: (offerTopic as any).topic_id,
            title: offerTopic.title,
          });
        } else {
          console.log('[GroupDetailPage.loadTopics] Offer topic not found in API client data');
        }
      } catch (e) {
        console.warn('[GroupDetailPage.loadTopics] debug Offer topic failed:', e);
      }

      setTopics(data.data);
      setTotalPages(data.pagination.pages);
      setTopicsLoading(false);

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : '加载话题列表失败';

      // 如果是API保护机制导致的错误，自动重试
      if (errorMessage.includes('未知错误') || errorMessage.includes('空数据') || errorMessage.includes('反爬虫')) {
        const nextRetryCount = currentRetryCount + 1;
        const delay = Math.min(1000 + (nextRetryCount * 300), 3000); // 递增延迟，最大3秒



        setTimeout(() => {
          loadTopics(nextRetryCount);
        }, delay);
        return;
      }

      console.error('加载话题列表失败:', err);
      setTopicsLoading(false);
    }
  };



  const loadRecentTasks = async () => {
    try {
      const tasks = await apiClient.getTasks();
      // 只显示最近的5个任务
      setRecentTasks(tasks.slice(0, 5));
    } catch (err) {
      console.error('加载任务列表失败:', err);
    }
  };

  const loadGroupInfo = async () => {
    try {
      const info = await apiClient.getGroupInfo(groupId);
      setGroupInfo(info);
    } catch (error) {
      console.error('加载群组信息失败:', error);
    }
  };

  const loadLocalFileCount = async () => {
    try {
      const stats = await apiClient.getFileStats(groupId);
      // 使用特定群组的文件统计数据
      setLocalFileCount(stats.download_stats.total_files || 0);
    } catch (error) {
      console.error('加载本地文件数量失败:', error);
      // 如果API调用失败，设置为0
      setLocalFileCount(0);
    }
  };

  const loadTags = async () => {
    setTagsLoading(true);
    try {
      const data = await apiClient.getGroupTags(groupId);
      setTags(data.tags || []);
    } catch (error) {
      console.error('Failed to load tags:', error);
    } finally {
      setTagsLoading(false);
    }
  };

  // 加载账号列表
  const loadAccounts = async () => {
    try {
      const res = await apiClient.listAccounts();
      setAccounts(res.accounts || []);
    } catch (err) {
      console.error('加载账号列表失败:', err);
    }
  };

  // 加载群组绑定账号
  const loadGroupAccount = async () => {
    try {
      const res = await apiClient.getGroupAccount(groupId);
      const acc = (res as any)?.account || null;
      setGroupAccount(acc);
      setSelectedAccountId(acc?.id || '');
    } catch (err) {
      console.error('加载群组账号失败:', err);
    }
  };

  // 加载群组所属账号的自我信息（持久化）
  const loadGroupAccountSelf = async () => {
    try {
      setLoadingAccountSelf(true);
      const res = await apiClient.getGroupAccountSelf(groupId);
      setAccountSelf((res as any)?.self || null);
    } catch (err) {
      console.error('加载账号用户信息失败:', err);
    } finally {
      setLoadingAccountSelf(false);
    }
  };

  // 刷新群组所属账号的自我信息（强制抓取）
  const refreshGroupAccountSelf = async () => {
    try {
      setRefreshingAccountSelf(true);
      const res = await apiClient.refreshGroupAccountSelf(groupId);
      setAccountSelf((res as any)?.self || null);
      toast.success('已刷新账号用户信息');
    } catch (err) {
      toast.error('刷新账号信息失败');
      console.error('刷新账号用户信息失败:', err);
    } finally {
      setRefreshingAccountSelf(false);
    }
  };

  // 绑定账号到当前群组
  const handleAssignAccount = async () => {
    if (!selectedAccountId) {
      toast.error('请选择要绑定的账号');
      return;
    }
    setAssigningAccount(true);
    try {
      await apiClient.assignGroupAccount(groupId, selectedAccountId);
      toast.success('已绑定账号到该群组');
      await loadGroupAccount();
      await loadGroupAccountSelf();
    } catch (err) {
      toast.error('绑定失败');
      console.error('绑定账号失败:', err);
    } finally {
      setAssigningAccount(false);
    }
  };

  // 爬取操作函数
  const handleCrawlLatest = async () => {
    try {
      setLatestDialogOpen(false);
      setCrawlLoading('latest');

      // 构建爬取设置参数
      const crawlSettings = {
        crawlIntervalMin,
        crawlIntervalMax,
        longSleepIntervalMin: crawlLongSleepIntervalMin,
        longSleepIntervalMax: crawlLongSleepIntervalMax,
        pagesPerBatch: Math.max(crawlPagesPerBatch, 5)
      };

      const response = await apiClient.crawlLatestUntilComplete(groupId, crawlSettings);
      toast.success(`任务已创建: ${(response as any).task_id}`);

      // 设置当前任务ID以显示日志
      setCurrentTaskId((response as any).task_id);
      // 自动切换到日志标签页
      setActiveTab('logs');

      setTimeout(() => {
        loadGroupStats();
        loadTopics();
        loadRecentTasks();
      }, 2000);
    } catch (error) {
      toast.error(`创建任务失败: ${error instanceof Error ? error.message : '未知错误'}`);
    } finally {
      setCrawlLoading(null);
    }
  };

  const handleCrawlAll = async () => {
    try {
      setCrawlLoading('all');

      // 构建爬取设置参数
      const crawlSettings = {
        crawlIntervalMin,
        crawlIntervalMax,
        longSleepIntervalMin: crawlLongSleepIntervalMin,
        longSleepIntervalMax: crawlLongSleepIntervalMax,
        pagesPerBatch: Math.max(crawlPagesPerBatch, 5)
      };

      const response = await apiClient.crawlAll(groupId, crawlSettings);
      toast.success(`任务已创建: ${(response as any).task_id}`);

      // 设置当前任务ID以显示日志
      setCurrentTaskId((response as any).task_id);
      // 自动切换到日志标签页
      setActiveTab('logs');

      setTimeout(() => {
        loadGroupStats();
        loadTopics();
        loadRecentTasks();
      }, 2000);
    } catch (error) {
      toast.error(`创建任务失败: ${error instanceof Error ? error.message : '未知错误'}`);
    } finally {
      setCrawlLoading(null);
    }
  };

  // 在 handleIncrementalCrawl 函数之后添加（约第560行）：
  
    const handleIncrementalCrawl = async () => {
    try {
      setCrawlLoading('incremental');

      // 构建爬取设置参数
    const crawlSettings = {
      crawlIntervalMin,
      crawlIntervalMax,
      longSleepIntervalMin: crawlLongSleepIntervalMin,
      longSleepIntervalMax: crawlLongSleepIntervalMax,
      pagesPerBatch: Math.max(crawlPagesPerBatch, 5)
    };

    const response = await apiClient.crawlIncremental(groupId, 10, 20, crawlSettings);
    toast.success(`增量爬取任务已创建: ${(response as any).task_id}`);

    // 设置当前任务ID以显示日志
    setCurrentTaskId((response as any).task_id);
    // 自动切换到日志标签页
    setActiveTab('logs');

    setTimeout(() => {
      loadGroupStats();
      loadTopics();
      loadRecentTasks();
    }, 2000);
  } catch (error) {
    toast.error(`增量爬取失败: ${error instanceof Error ? error.message : '未知错误'}`);
  } finally {
    setCrawlLoading(null);
  }
};    
      
  const handleScheduledCrawl = async () => {
    try {
      setCrawlLoading('scheduled');
      
      if (!scheduledRunning) {
        // 启动定时任务
        const settings = {
          intervalMinutes: scheduleIntervalMinutes,
          crawlIntervalMin,
          crawlIntervalMax,
          longSleepIntervalMin: crawlLongSleepIntervalMin,
          longSleepIntervalMax: crawlLongSleepIntervalMax,
          pagesPerBatch: Math.max(crawlPagesPerBatch, 5)
        };
        
        const response = await apiClient.startScheduledCrawl(groupId, settings);
        toast.success(`定时任务已启动: ${(response as any).task_id || '成功'}`);
        setScheduledRunning(true);
        
        // 设置当前任务ID以显示日志
        setCurrentTaskId((response as any).task_id);
        // 自动切换到日志标签页
        setActiveTab('logs');
      } else {
        // 停止定时任务
        await apiClient.stopScheduledCrawl(groupId);
        toast.success('定时任务已停止');
        setScheduledRunning(false);
      }
    } catch (err) {
      toast.error(`操作失败: ${err instanceof Error ? err.message : '未知错误'}`);
    } finally {
      setCrawlLoading(null);
    }
  };
  const handleCrawlRange = async () => {
    try {
      setLatestDialogOpen(false);
      setCrawlLoading('range');

      const params: any = {};

      // 优先使用自定义日期范围；否则使用最近N天
      if (rangeStartDate || rangeEndDate) {
        if (rangeStartDate) params.startTime = rangeStartDate; // YYYY-MM-DD
        if (rangeEndDate) params.endTime = rangeEndDate;       // YYYY-MM-DD
      } else {
        params.lastDays = Math.max(1, quickLastDays || 1);
      }

      // 传递当前的爬取间隔设置
      params.crawlIntervalMin = crawlIntervalMin;
      params.crawlIntervalMax = crawlIntervalMax;
      params.longSleepIntervalMin = crawlLongSleepIntervalMin;
      params.longSleepIntervalMax = crawlLongSleepIntervalMax;
      params.pagesPerBatch = Math.max(crawlPagesPerBatch, 5);

      const response = await apiClient.crawlByTimeRange(groupId, params);
      toast.success(`任务已创建: ${(response as any).task_id}`);

      // 日志联动
      setCurrentTaskId((response as any).task_id);
      setActiveTab('logs');

      setTimeout(() => {
        loadGroupStats();
        loadTopics();
        loadRecentTasks();
      }, 2000);
    } catch (error) {
      toast.error(`创建任务失败: ${error instanceof Error ? error.message : '未知错误'}`);
    } finally {
      setCrawlLoading(null);
    }
  };

  // 单个话题采集
  const handleFetchSingleTopic = async () => {
    if (!singleTopicId || isNaN(parseInt(singleTopicId))) {
      toast.error('请输入有效的话题ID');
      return;
    }
    setFetchingSingle(true);
    try {
      const tid = parseInt(singleTopicId);
      const res = await apiClient.fetchSingleTopic(groupId, tid);
      toast.success(`已采集话题 ${tid}（${(res as any)?.imported || 'ok'}）`);
      // 采集完成后刷新话题列表/统计
      setTimeout(() => {
        loadGroupStats();
        loadTopics();
      }, 800);
    } catch (error) {
      toast.error(`采集失败: ${error instanceof Error ? error.message : '未知错误'}`);
    } finally {
      setFetchingSingle(false);
    }
  };

  // 文件操作函数
  const handleCollectFiles = async () => {
    try {
      setFileLoading('collect');
      const response = await apiClient.collectFiles(groupId);
      toast.success(`文件收集任务已创建: ${(response as any).task_id}`);
      // 设置当前任务ID以显示日志
      setCurrentTaskId((response as any).task_id);
      // 自动切换到日志标签页
      setActiveTab('logs');
    } catch (error) {
      toast.error(`文件收集失败: ${error instanceof Error ? error.message : '未知错误'}`);
    } finally {
      setFileLoading(null);
    }
  };

  const handleDownloadByTime = async () => {
    try {
      setFileLoading('download-time');
      const response = await apiClient.downloadFiles(
        groupId,
        undefined,
        'create_time',
        downloadInterval,
        longSleepInterval,
        filesPerBatch,
        useRandomInterval ? downloadIntervalMin : undefined,
        useRandomInterval ? downloadIntervalMax : undefined,
        useRandomInterval ? longSleepIntervalMin : undefined,
        useRandomInterval ? longSleepIntervalMax : undefined
      );
      toast.success(`文件下载任务已创建: ${(response as any).task_id}`);
      // 设置当前任务ID以显示日志
      setCurrentTaskId((response as any).task_id);
      // 自动切换到日志标签页
      setActiveTab('logs');
    } catch (error) {
      toast.error(`文件下载失败: ${error instanceof Error ? error.message : '未知错误'}`);
    } finally {
      setFileLoading(null);
    }
  };

  const handleDownloadByCount = async () => {
    try {
      setFileLoading('download-count');
      const response = await apiClient.downloadFiles(
        groupId,
        undefined,
        'download_count',
        downloadInterval,
        longSleepInterval,
        filesPerBatch,
        useRandomInterval ? downloadIntervalMin : undefined,
        useRandomInterval ? downloadIntervalMax : undefined,
        useRandomInterval ? longSleepIntervalMin : undefined,
        useRandomInterval ? longSleepIntervalMax : undefined
      );
      toast.success(`文件下载任务已创建: ${(response as any).task_id}`);
      // 设置当前任务ID以显示日志
      setCurrentTaskId((response as any).task_id);
      // 自动切换到日志标签页
      setActiveTab('logs');
    } catch (error) {
      toast.error(`文件下载失败: ${error instanceof Error ? error.message : '未知错误'}`);
    } finally {
      setFileLoading(null);
    }
  };

  const handleClearFileDatabase = async () => {
    try {
      setFileLoading('clear');
      const response = await apiClient.clearFileDatabase(groupId);
      toast.success(`文件数据库已删除`);
      // 重新加载本地文件数量
      loadLocalFileCount();
    } catch (error) {
      toast.error(`删除文件数据库失败: ${error instanceof Error ? error.message : '未知错误'}`);
    } finally {
      setFileLoading(null);
    }
  };

  const handleSettingsChange = (settings: {
    downloadInterval: number;
    longSleepInterval: number;
    filesPerBatch: number;
    downloadIntervalMin?: number;
    downloadIntervalMax?: number;
    longSleepIntervalMin?: number;
    longSleepIntervalMax?: number;
  }) => {
    setDownloadInterval(settings.downloadInterval);
    setLongSleepInterval(settings.longSleepInterval);
    setFilesPerBatch(settings.filesPerBatch);

    // 更新随机间隔设置
    if (settings.downloadIntervalMin !== undefined) {
      setDownloadIntervalMin(settings.downloadIntervalMin);
      setDownloadIntervalMax(settings.downloadIntervalMax || 30);
      setLongSleepIntervalMin(settings.longSleepIntervalMin || 30);
      setLongSleepIntervalMax(settings.longSleepIntervalMax || 60);
      setUseRandomInterval(true);
    } else {
      setUseRandomInterval(false);
    }

    toast.success('下载设置已更新');
  };

  // 删除话题数据库
  const handleDeleteTopics = async () => {
    try {
      // 使用正确的清除话题数据库API
      await apiClient.clearTopicDatabase(groupId);

      toast.success('话题数据已删除');

      // 重新加载数据
      loadGroupStats();
      loadTopics();
      loadTags(); // 重新加载标签

      // 重置选择状态
      setSelectedCrawlOption('all');
      setSelectedTag(null); // 重置标签选择
    } catch (error) {
      toast.error(`删除失败: ${error instanceof Error ? error.message : '未知错误'}`);
    }
  };

    // 切换评论展开状态
  const toggleComments = (topicId: number | string) => {
    const id = String(topicId);  // 转换为 string
    setExpandedComments(prev => {
      const newSet = new Set(prev);
      if (newSet.has(id)) {
        newSet.delete(id);
      } else {
        newSet.add(id);
      }
      return newSet;
    });
  };



  // 刷新单个话题
  const refreshSingleTopic = async (topicId: number) => {
    if (refreshingTopics.has(topicId)) {
      return; // 防止重复请求
    }

    setRefreshingTopics(prev => new Set(prev).add(topicId));

    try {
      const response = await apiClient.refreshTopic(topicId, groupId);

      if (response.success) {
        toast.success(`${response.message} - 点赞:${response.updated_data.likes_count} 评论:${response.updated_data.comments_count}`);

        // 更新当前话题列表中的数据，而不是重新加载整个列表
        setTopics(prevTopics =>
          prevTopics.map(topic =>
            parseInt(topic.topic_id.toString()) === parseInt(topicId.toString())
              ? {
                  ...topic,
                  likes_count: response.updated_data.likes_count,
                  comments_count: response.updated_data.comments_count,
                  reading_count: response.updated_data.reading_count,
                  readers_count: response.updated_data.readers_count,
                  imported_at: new Date().toISOString() // 更新获取时间
                }
              : topic
          )
        );
      } else {
        toast.error(response.message || '刷新话题失败');
      }
    } catch (error) {
      toast.error('刷新话题失败');
      console.error('刷新话题失败:', error);
    } finally {
      setRefreshingTopics(prev => {
        const newSet = new Set(prev);
        newSet.delete(topicId);
        return newSet;
      });
    }
  };

  // 删除单个话题（改用自定义弹窗，保留方法以兼容可能的调用）
  const handleDeleteSingleTopic = async (topicId: number) => {
    await deleteSingleTopicConfirmed(topicId);
  };

  // 删除单个话题（自定义弹窗调用，无浏览器确认）
  const deleteSingleTopicConfirmed = async (topicId: number) => {
    setDeletingTopics(prev => new Set(prev).add(topicId));
    try {
      const res = await apiClient.deleteSingleTopic(groupId, topicId) as any;
      if (res && res.success) {
        // 从当前列表移除
        setTopics(prev =>
          prev.filter(t => parseInt(t.topic_id.toString()) !== parseInt(topicId.toString()))
        );
        toast.success('话题已删除');
        // 刷新统计与标签
        loadGroupStats();
        loadTags();
      } else {
        toast.error(res?.message || '删除失败');
      }
    } catch (err) {
      toast.error('删除失败');
      console.error('删除话题失败:', err);
    } finally {
      setDeletingTopics(prev => {
        const s = new Set(prev);
        s.delete(topicId);
        return s;
      });
    }
  };

  // 加载缓存信息
  const loadCacheInfo = async () => {
    try {
      const info = await apiClient.getImageCacheInfo(groupId.toString());
      setCacheInfo(info);
    } catch (error) {
      console.error('加载缓存信息失败:', error);
    }
  };

  // 加载专栏摘要信息
  const loadColumnsSummary = async () => {
    try {
      const summary = await apiClient.getGroupColumnsSummary(groupId);
      setHasColumns(summary.has_columns);
      setColumnsTitle(summary.title);
    } catch (error) {
      console.error('加载专栏信息失败:', error);
      setHasColumns(false);
      setColumnsTitle(null);
    }
  };

  // 清空图片缓存（使用自定义弹窗，不再重复浏览器确认）
  const clearImageCache = async () => {
    setClearingCache(true);
    try {
      const response = await apiClient.clearImageCache(groupId.toString());
      if (response.success) {
        toast.success(response.message);
        await loadCacheInfo(); // 重新加载缓存信息
      } else {
        toast.error('清空缓存失败');
      }
    } catch (error) {
      toast.error('清空缓存失败');
      console.error('清空缓存失败:', error);
    } finally {
      setClearingCache(false);
    }
  };

  // 处理话题爬取设置变更
  const handleCrawlSettingsChange = (settings: {
    crawlInterval: number;
    longSleepInterval: number;
    pagesPerBatch: number;
    crawlIntervalMin?: number;
    crawlIntervalMax?: number;
    longSleepIntervalMin?: number;
    longSleepIntervalMax?: number;
  }) => {
    setCrawlInterval(settings.crawlInterval);
    setCrawlLongSleepInterval(settings.longSleepInterval);
    setCrawlPagesPerBatch(settings.pagesPerBatch);

    // 保存间隔参数
    setCrawlIntervalMin(settings.crawlIntervalMin || 2);
    setCrawlIntervalMax(settings.crawlIntervalMax || 5);
    setCrawlLongSleepIntervalMin(settings.longSleepIntervalMin || 180);
    setCrawlLongSleepIntervalMax(settings.longSleepIntervalMax || 300);

    toast.success('话题爬取设置已更新');
  };

  // 获取更多评论
  const fetchMoreComments = async (topicId: number) => {
    if (fetchingComments.has(topicId)) {
      return; // 防止重复请求
    }

    setFetchingComments(prev => new Set(prev).add(topicId));

    try {
      const response = await fetch(`/api/topics/${topicId}/${groupId}/fetch-comments`, {
        method: 'POST',
      });

      if (response.ok) {
        const result = await response.json();
        toast.success(result.message);

        // 重新加载话题数据以显示新评论
        if (result.comments_fetched > 0) {
          await loadTopics();
        }
      } else {
        const error = await response.json();
        toast.error(error.detail || '获取评论失败');
      }
    } catch (error) {
      toast.error('获取评论失败');
      console.error('获取评论失败:', error);
    } finally {
      setFetchingComments(prev => {
        const newSet = new Set(prev);
        newSet.delete(topicId);
        return newSet;
      });
    }
  };

  // 获取文件状态
  const getFileStatus = useCallback(async (fileId: number, fileName?: string, fileSize?: number) => {
    try {
      // 首先尝试从数据库获取文件状态
      const status = await apiClient.getFileStatus(groupId.toString(), fileId) as FileStatus;
      setFileStatuses(prev => new Map(prev).set(fileId, status));
      return status;
    } catch (error) {
      console.error('从数据库获取文件状态失败:', error);

      // 如果数据库中没有文件，但有文件名和大小，检查本地文件
      if (fileName && fileSize !== undefined) {
        try {
          const localStatus = await apiClient.checkLocalFileStatus(groupId.toString(), fileName, fileSize) as any;
          const status: FileStatus = {
            file_id: fileId,
            name: fileName,
            size: fileSize,
            download_status: localStatus.is_complete ? 'downloaded' : 'not_collected',
            local_exists: localStatus.local_exists,
            local_size: localStatus.local_size,
            local_path: localStatus.local_path,
            is_complete: localStatus.is_complete
          };
          setFileStatuses(prev => new Map(prev).set(fileId, status));
          return status;
        } catch (localError) {
          console.error('检查本地文件失败:', localError);
        }
      }

      // 如果都失败了，设置默认状态
      const defaultStatus: FileStatus = {
        file_id: fileId,
        name: fileName || '',
        size: fileSize || 0,
        download_status: 'not_collected',
        local_exists: false,
        local_size: 0,
        is_complete: false
      };
      setFileStatuses(prev => new Map(prev).set(fileId, defaultStatus));
      return defaultStatus;
    }
  }, [groupId]);

  // 下载单个文件
  const downloadSingleFile = async (fileId: number, fileName: string, fileSize?: number) => {
    if (downloadingFiles.has(fileId)) {
      return; // 防止重复下载
    }

    setDownloadingFiles(prev => new Set(prev).add(fileId));

    try {
      const response = await apiClient.downloadSingleFile(groupId.toString(), fileId, fileName, fileSize) as any;
      toast.success(`文件下载任务已创建: ${response.task_id}`);

      // 设置当前任务ID以显示日志
      setCurrentTaskId(response.task_id);
      // 自动切换到日志标签页
      setActiveTab('logs');

      // 定期检查文件状态
      const checkStatus = async () => {
        const status = await getFileStatus(fileId, fileName, fileSize);
        if (status && status.is_complete) {
          toast.success(`文件下载完成: ${fileName}`);
          // 强制刷新文件状态以显示路径
          setFileStatuses(prev => new Map(prev).set(fileId, status));
          return true;
        }
        return false;
      };

      // 每5秒检查一次状态，最多检查12次（1分钟）
      let attempts = 0;
      const statusInterval = setInterval(async () => {
        attempts++;
        const completed = await checkStatus();
        if (completed || attempts >= 12) {
          clearInterval(statusInterval);
        }
      }, 5000);

    } catch (error) {
      toast.error(`文件下载失败: ${error instanceof Error ? error.message : '未知错误'}`);
    } finally {
      setDownloadingFiles(prev => {
        const newSet = new Set(prev);
        newSet.delete(fileId);
        return newSet;
      });
    }
  };

    // 切换内容展开状态
  const toggleContent = (topicId: number | string) => {
    const id = String(topicId);  // 转换为 string
    setExpandedContent(prev => {
      const newSet = new Set(prev);
      if (newSet.has(id)) {
        newSet.delete(id);
      } else {
        newSet.add(id);
      }
      return newSet;
    });
  };



  const getTypeBadge = (type: string) => {
    switch (type) {
      case 'private':
        return <Badge variant="secondary" className="text-xs px-1.5 py-0.5">私密</Badge>;
      case 'public':
        return <Badge variant="secondary" className="text-xs px-1.5 py-0.5">公开</Badge>;
      case 'pay':
        return <Badge className="bg-orange-100 text-orange-800 text-xs px-1.5 py-0.5">付费</Badge>;
      default:
        return <Badge variant="secondary" className="text-xs px-1.5 py-0.5">未知</Badge>;
    }
  };

  const getStatusBadge = (status?: string) => {
    switch (status) {
      case 'active':
        return <Badge className="bg-green-100 text-green-800 text-xs">活跃</Badge>;
      case 'expiring_soon':
        return <Badge className="bg-yellow-100 text-yellow-800 text-xs">即将到期</Badge>;
      case 'expired':
        return <Badge className="bg-red-100 text-red-800 text-xs">已过期</Badge>;
      default:
        return null;
    }
  };

  const formatDate = (dateString?: string) => {
    if (!dateString) return '';
    try {
      return new Date(dateString).toLocaleDateString('zh-CN');
    } catch {
      return '';
    }
  };

  const formatDateTime = (dateString: string) => {
    if (!dateString) return '未知时间';
    try {
      const date = new Date(dateString);
      return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return '时间格式错误';
    }
  };

  // 格式化获取时间
  const formatImportedTime = (importedAt: string) => {
    if (!importedAt) return '';
    try {
      const date = new Date(importedAt);
      return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
      });
    } catch (error) {
      return importedAt;
    }
  };

  // 话题卡片组件
  const TopicCard = ({ topic, searchTerm, topicDetail }: { topic: any; searchTerm?: string; topicDetail?: any }) => {
    const cardRef = useRef<HTMLDivElement>(null);
    const contentRef = useRef<HTMLDivElement>(null);

    // 检测是否为被过滤的内容
    const isFiltered = topic._filtered === true;

    // 详情由父组件预取并通过 props 提供

    return (
      <div
    ref={cardRef}
    className={`border shadow-none w-full max-w-full bg-white rounded-lg relative ${isFiltered ? 'border-gray-300 opacity-75' : 'border-gray-200'}`}
    style={{width: '100%', maxWidth: '100%', boxSizing: 'border-box'}}
  >
    {/* 被过滤内容的遮罩提示 */}
    {isFiltered && (
      <div 
        className="absolute inset-0 bg-gray-100/60 backdrop-blur-[2px] rounded-lg z-50 flex items-center justify-center"
        style={{ pointerEvents: 'auto' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="bg-white/95 border border-gray-300 rounded-lg p-6 shadow-lg max-w-xs mx-4 text-center">
          <div className="text-4xl mb-3">🔒</div>
          <div className="text-base font-semibold text-gray-800 mb-2">
            📢 该内容仅对付费用户开放
          </div>
          <div className="text-sm text-gray-600 mb-2">
            免费用户仅可查看 7 天前的内容
          </div>
          <div className="text-sm text-blue-600 font-medium">
            升级会员可查看更多
          </div>
        </div>
      </div>
    )}

        <div className="p-4 w-full max-w-full" style={{width: '100%', maxWidth: '100%', boxSizing: 'border-box'}}>
          <div className="space-y-3 w-full">
            {/* 作者信息和徽章 */}
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-2">
                {/* 根据话题类型显示不同的作者信息 */}
                {topic.type === 'q&a' ? (
                  // 问答类型显示回答者信息
                  topicDetail?.answer?.owner && (
                    <>
                      <img
                        src={apiClient.getProxyImageUrl(topicDetail.answer.owner.avatar_url, groupId.toString())}
                        alt={topicDetail.answer.owner.name}
                        loading="lazy"
                        decoding="async"
                        className="w-8 h-8 rounded-full object-cover block"
                        onError={(e) => {
                          e.currentTarget.src = '/default-avatar.png';
                        }}
                      />
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-gray-900">
                            {topicDetail.answer.owner.name}
                          </span>
                          {/* IP信息放在姓名右边 */}
                          {topicDetail.answer.owner.location && (
                            <span className="text-xs text-gray-400">
                              来自 {topicDetail.answer.owner.location}
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-gray-500">
                          {formatDateTime(topic.create_time)}
                        </div>
                      </div>
                    </>
                  )
                ) : (
                  // 其他类型显示原作者信息
                  topic.author && (
                    <>
                      <img
                        src={apiClient.getProxyImageUrl(topic.author.avatar_url, groupId.toString())}
                        alt={topic.author.name}
                        loading="lazy"
                        decoding="async"
                        className="w-8 h-8 rounded-full object-cover block"
                        onError={(e) => {
                          e.currentTarget.src = '/default-avatar.png';
                        }}
                      />
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-medium text-gray-900">
                            {topic.author.name}
                          </span>
                          {/* IP信息放在姓名右边 */}
                          {topicDetail?.talk?.owner?.location && (
                            <span className="text-xs text-gray-400">
                              来自 {topicDetail.talk.owner.location}
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-gray-500">
                          {formatDateTime(topic.create_time)}
                        </div>
                      </div>
                    </>
                  )
                )}
              </div>
              <div className="flex flex-col items-end gap-1">
                {/* 徽章和刷新按钮 */}
                <div className="flex items-center gap-2">
                  <Badge variant="secondary" className="text-xs">
                    {topic.type}
                  </Badge>
                  {topic.sticky && (
                    <Badge variant="outline" className="text-xs text-red-600 border-red-200">
                      置顶
                    </Badge>
                  )}
                  {topic.digested && (
                    <Badge variant="outline" className="text-xs text-green-600 border-green-200">
                      精华
                    </Badge>
                  )}

                  {/* 刷新按钮 */}
                  <button type="button"
                    onClick={() => refreshSingleTopic(topic.topic_id)}
                    disabled={refreshingTopics.has(topic.topic_id)}
                    className="flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 disabled:text-gray-400 transition-colors ml-2"
                    title="从服务器重新获取最新数据"
                  >
                    <RotateCcw className={`w-3 h-3 ${refreshingTopics.has(topic.topic_id) ? 'animate-spin' : ''}`} />
                    {refreshingTopics.has(topic.topic_id) ? '获取中' : '远程刷新'}
                  </button>

                  {/* 删除按钮（自定义弹窗确认） */}
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <button
                        type="button"
                        disabled={deletingTopics.has(topic.topic_id)}
                        className="flex items-center gap-1 text-xs text-red-600 hover:text-red-800 disabled:text-gray-400 transition-colors ml-2"
                        title="删除该话题（本地数据库）"
                      >
                        <Trash2 className="w-3 h-3" />
                        {deletingTopics.has(topic.topic_id) ? '删除中' : '删除'}
                      </button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle className="text-red-600">确认删除该话题</AlertDialogTitle>
                        <AlertDialogDescription className="text-red-700">
                          此操作将永久删除该话题及其所有关联数据（评论、用户信息等），且不可恢复。确定要继续吗？
                        </AlertDialogDescription>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>取消</AlertDialogCancel>
                        <AlertDialogAction
                          onClick={() => deleteSingleTopicConfirmed(topic.topic_id)}
                          className="bg-red-600 hover:bg-red-700 focus:ring-red-600"
                        >
                          确认删除
                        </AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                </div>

                {/* 获取时间信息 */}
                {topic.imported_at && (
                  <div className="text-xs text-gray-400 flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    <span>获取于: {formatImportedTime(topic.imported_at)}</span>
                  </div>
                )}
              </div>
            </div>

            {/* 话题内容 */}
            <div className="space-y-3 w-full overflow-hidden">
              {topic.type === 'q&a' ? (
                // 问答类型话题 - 采用官网样式
                <div className="space-y-4">
                  {/* 问题部分 */}
                  {(topic.question_text || topicDetail?.question?.text) && (
                    <div className="w-full max-w-full overflow-hidden" style={{minWidth: 0}}>
                      {/* 提问者信息 */}
                      <div className="text-sm text-gray-600 mb-2">
                        <span className="font-medium">
                          {topicDetail?.question?.anonymous ? '匿名用户' :
                           topicDetail?.question?.owner?.name || '用户'} 提问：
                        </span>
                        {/* 匿名用户的IP信息 */}
                        {topicDetail?.question?.anonymous && topicDetail?.question?.owner_location && (
                          <span className="text-xs text-gray-400 ml-2">
                            来自 {topicDetail.question.owner_location}
                          </span>
                        )}
                      </div>

                      {/* 问题内容 - 使用引用样式，文字颜色更淡 */}
                      <div className="bg-gray-50 border-l-4 border-gray-300 pl-4 py-3 rounded-r-lg w-full max-w-full overflow-hidden" style={{minWidth: 0}}>
                        <div
                          className="text-sm text-gray-500 whitespace-pre-wrap break-words break-all leading-relaxed prose prose-sm max-w-none prose-p:my-1 prose-strong:text-gray-700 prose-a:text-blue-500 prose-a:align-middle"
                          style={{wordBreak: 'break-all', overflowWrap: 'anywhere'}}
                          dangerouslySetInnerHTML={createSafeHtmlWithHighlight(topic.question_text || topicDetail?.question?.text || '', searchTerm)}
                        />
                      </div>
                      {/* 问题图片 */}
                      {topicDetail?.question?.images && topicDetail.question.images.length > 0 && (
                        <div className="mt-3">
                          <ImageGallery
                            images={topicDetail.question.images}
                            size="small"
                            groupId={groupId.toString()}
                          />
                        </div>
                      )}

                    </div>
                  )}

                  {/* 回答部分 - 不再显示头像，因为已经在顶部显示了 */}
                  {(topic.answer_text || topicDetail?.answer?.text) && (
                    <div className="w-full">
                      <div className="w-full max-w-full overflow-hidden" style={{minWidth: 0}}>
                        <div
                          className={`text-sm text-gray-800 whitespace-pre-wrap break-words break-all leading-relaxed prose prose-sm max-w-none prose-p:my-1 prose-strong:text-gray-900 prose-a:text-blue-600 ${
                            !expandedContent.has(topic.topic_id) ? 'line-clamp-8' : ''
                          }`}
                          style={{
                            wordBreak: 'break-all',
                            overflowWrap: 'anywhere'
                          }}
                          dangerouslySetInnerHTML={createSafeHtmlWithHighlight(topic.answer_text || topicDetail?.answer?.text || '', searchTerm)}
                        />
                      </div>
                      {(extractPlainText(topic.answer_text || topicDetail?.answer?.text || '').split('\n').length > 4 || extractPlainText(topic.answer_text || topicDetail?.answer?.text || '').length > 300) && (
                        <div className="text-center mt-2">
                          <button type="button"
                            onClick={() => toggleContent(topic.topic_id)}
                            className="text-xs text-blue-600 hover:text-blue-800 font-medium transition-colors"
                          >
                            {expandedContent.has(topic.topic_id) ? '收起' : '展开全部'}
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                  {/* 回答图片 */}
                  {topicDetail?.answer?.images && topicDetail.answer.images.length > 0 && (
                    <div className="mt-3">
                      <ImageGallery
                        images={topicDetail.answer.images}
                        size="small"
                        groupId={groupId.toString()}
                      />
                    </div>
                  )}

                </div>
              ) : (
                // 其他类型话题
                <div className="w-full">
                  {topic.talk_text ? (
                    <div className="w-full">
                      <div ref={contentRef} className="bg-gray-50 rounded-lg p-3 w-full max-w-full overflow-hidden" style={{minWidth: 0}}>
                        <div
                          className={`text-sm text-gray-800 whitespace-pre-wrap break-words break-all prose prose-sm max-w-none prose-p:my-1 prose-strong:text-gray-900 prose-a:text-blue-600 ${
                            !expandedContent.has(topic.topic_id) ? 'line-clamp-8' : ''
                          }`}
                          style={{wordBreak: 'break-all', overflowWrap: 'anywhere'}}
                          dangerouslySetInnerHTML={createSafeHtmlWithHighlight(topic.talk_text, searchTerm)}
                        />
                      </div>
                      {(extractPlainText(topic.talk_text).split('\n').length > 4 || extractPlainText(topic.talk_text).length > 300) && (
                        <div className="text-center mt-2">
                          <button type="button"
                            onClick={() => toggleContent(topic.topic_id)}
                            className="text-xs text-blue-600 hover:text-blue-800 font-medium transition-colors"
                          >
                            {expandedContent.has(topic.topic_id) ? '收起' : '展开全部'}
                          </button>
                        </div>
                      )}
                    </div>
                  ) : topic.title ? (
                    <div className="w-full">
                      <div className="bg-gray-50 rounded-lg p-3 w-full max-w-full overflow-hidden">
                        <div
                          className={`text-sm text-gray-800 break-words prose prose-sm max-w-none prose-p:my-1 prose-strong:text-gray-900 prose-a:text-blue-600 ${
                            !expandedContent.has(topic.topic_id) ? 'line-clamp-8' : ''
                          }`}
                          dangerouslySetInnerHTML={createSafeHtmlWithHighlight(topic.title, searchTerm)}
                        />
                      </div>
                      {topic.title && (extractPlainText(topic.title).split('\n').length > 4 || extractPlainText(topic.title).length > 300) && (
                        <div className="text-center mt-2">
                          <button type="button"
                            onClick={() => toggleContent(topic.topic_id)}
                            className="text-xs text-blue-600 hover:text-blue-800 font-medium transition-colors"
                          >
                            {expandedContent.has(topic.topic_id) ? '收起' : '展开全部'}
                          </button>
                        </div>
                      )}
                    </div>
                  ) : null}
                </div>
              )}
            </div>

            {/* 文章链接（适配 talk.article） */}
            {topicDetail?.talk?.article && (
              <div className="bg-blue-50 border border-blue-200 rounded-md p-2 mt-2">
                <a
                  href={(topicDetail.talk.article.article_url || topicDetail.talk.article.inline_article_url) as string}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-blue-600 hover:text-blue-800 inline-flex items-center gap-1"
                  title={topicDetail.talk.article.title || '查看文章'}
                >
                  <ExternalLink className="w-3 h-3" />
                  {topicDetail.talk.article.title || '查看文章'}
                </a>
              </div>
            )}

            {/* 话题图片 */}
            {topicDetail?.talk?.images && topicDetail.talk.images.length > 0 && (
              <ImageGallery
                images={topicDetail.talk.images}
                className="w-full max-w-full"
                groupId={groupId.toString()}
              />
            )}

            {/* 话题文件 */}
            {topicDetail?.talk?.files && topicDetail.talk.files.length > 0 && (
              <div className="space-y-2 w-full max-w-full overflow-hidden" style={{width: '100%', maxWidth: '100%', boxSizing: 'border-box'}}>
                <div className="space-y-2">
                  {topicDetail.talk.files.map((file: any) => {
                    // 根据文件扩展名获取图标组件
                    const getFileIcon = (fileName: string) => {
                      const ext = fileName.split('.').pop()?.toLowerCase();
                      const iconProps = { className: "w-6 h-6 text-gray-600" };

                      switch (ext) {
                        case 'pdf':
                          return <FileText {...iconProps} className="w-6 h-6 text-red-600" />;
                        case 'doc':
                        case 'docx':
                          return <FileText {...iconProps} className="w-6 h-6 text-blue-600" />;
                        case 'xls':
                        case 'xlsx':
                          return <FileText {...iconProps} className="w-6 h-6 text-green-600" />;
                        case 'ppt':
                        case 'pptx':
                          return <FileText {...iconProps} className="w-6 h-6 text-orange-600" />;
                        case 'zip':
                        case 'rar':
                        case '7z':
                          return <Archive {...iconProps} className="w-6 h-6 text-purple-600" />;
                        case 'jpg':
                        case 'jpeg':
                        case 'png':
                        case 'gif':
                          return <FileImage {...iconProps} className="w-6 h-6 text-pink-600" />;
                        case 'mp4':
                        case 'avi':
                        case 'mov':
                          return <FileVideo {...iconProps} className="w-6 h-6 text-indigo-600" />;
                        case 'mp3':
                        case 'wav':
                        case 'flac':
                          return <FileAudio {...iconProps} className="w-6 h-6 text-yellow-600" />;
                        case 'txt':
                          return <FileText {...iconProps} />;
                        default:
                          return <File {...iconProps} />;
                      }
                    };

                    const formatFileSize = (bytes: number) => {
                      if (bytes === 0) return '0 B';
                      const k = 1024;
                      const sizes = ['B', 'KB', 'MB', 'GB'];
                      const i = Math.floor(Math.log(bytes) / Math.log(k));
                      return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
                    };

                    const fileStatus = fileStatuses.get(file.file_id);
                    const isDownloading = downloadingFiles.has(file.file_id);
                    const isDownloaded = fileStatus?.is_complete || false;

                    return (
                      <div key={file.file_id} className={`flex items-center gap-3 p-3 rounded-lg border ${
                        isDownloaded
                          ? 'bg-green-50 border-green-200'
                          : 'bg-gray-50 border-gray-200'
                      }`}>
                        <div className="flex-shrink-0">
                          {getFileIcon(file.name)}
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-medium text-gray-900 truncate" title={file.name}>
                            {file.name}
                          </div>
                          <div className="text-xs text-gray-500 flex items-center gap-2">
                            <span>{formatFileSize(file.size)}</span>
                            {file.download_count > 0 && (
                              <span>• 下载 {file.download_count} 次</span>
                            )}
                            {file.create_time && (
                              <span>• {formatDateTime(file.create_time)}</span>
                            )}
                            {/* 文件状态显示 */}
                            {fileStatus && (
                              <span className={`• ${
                                fileStatus.download_status === 'not_collected' ? 'text-gray-500' :
                                fileStatus.is_complete ? 'text-green-600' : 'text-orange-600'
                              }`}>
                                {fileStatus.download_status === 'not_collected' ? '未收集' :
                                 fileStatus.is_complete ? '已下载' : '未下载'}
                              </span>
                            )}
                          </div>
                          {/* 文件路径显示 */}
                          {fileStatus?.local_path && (
                            <div className="text-xs text-green-600 mt-1 truncate" title={fileStatus.local_path}>
                              📁 {fileStatus.local_path}
                            </div>
                          )}
                        </div>
                        <div className="flex-shrink-0">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={async () => {
                              // 点击时检查文件状态
                              const latestStatus = await getFileStatus(file.file_id, file.name, file.size);

                              if (latestStatus?.download_status === 'not_collected') {
                                toast.error('文件未收集，请先运行文件收集任务');
                                return;
                              }

                              // 如果文件已经下载完成，显示提示
                              if (latestStatus?.is_complete) {
                                toast.info(`文件已存在: ${latestStatus.local_path}`);
                                return;
                              }

                              downloadSingleFile(file.file_id, file.name, file.size);
                            }}
                            disabled={isDownloading}
                            className="flex items-center gap-1"
                          >
                            {isDownloading ? (
                              <>
                                <RefreshCw className="w-3 h-3 animate-spin" />
                                下载中
                              </>
                            ) : (
                              <>
                                <Download className="w-3 h-3" />
                                下载
                              </>
                            )}
                          </Button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* 评论 */}
            {topicDetail?.show_comments && topicDetail.show_comments.length > 0 && (() => {
              const isExpanded = expandedComments.has(topic.topic_id);
              const visibleCommentCount = isExpanded
                ? topicDetail.show_comments.length
                : calculateVisibleComments(topicDetail.show_comments);
              const commentsToShow = topicDetail.show_comments.slice(0, visibleCommentCount);

              return (
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-medium text-gray-600">
                      评论 ({topicDetail.comments_count || 0})
                    </h4>
                    {/* 获取更多评论按钮 */}
                    {(topicDetail.comments_count || 0) > 8 && (
                      <button type="button"
                        onClick={() => fetchMoreComments(topic.topic_id)}
                        disabled={fetchingComments.has(topic.topic_id)}
                        className="text-xs text-blue-600 hover:text-blue-800 disabled:text-gray-400 flex items-center gap-1"
                      >
                        {fetchingComments.has(topic.topic_id) ? (
                          <>
                            <RefreshCw className="w-3 h-3 animate-spin" />
                            获取中...
                          </>
                        ) : (
                          <>
                            <RefreshCw className="w-3 h-3" />
                            获取更多
                          </>
                        )}
                      </button>
                    )}
                  </div>
                  <div className="space-y-2">
                    {commentsToShow.map((comment: any) => (
                    <div key={comment.comment_id} className="bg-gray-50 rounded-lg p-2">
                      <div className="flex items-center gap-2 mb-1">
                        <img
                          src={apiClient.getProxyImageUrl(comment.owner.avatar_url, groupId.toString())}
                          alt={comment.owner.name}
                          loading="lazy"
                          decoding="async"
                          className="w-4 h-4 rounded-full object-cover block"
                          onError={(e) => {
                            e.currentTarget.src = '/default-avatar.png';
                          }}
                        />
                        <span className="text-xs font-medium text-gray-700">
                          {comment.owner.name}
                        </span>
                        {/* 显示回复关系 */}
                        {comment.repliee && (
                          <>
                            <span className="text-xs text-gray-400">回复</span>
                            <span className="text-xs font-medium text-blue-600">
                              {comment.repliee.name}
                            </span>
                          </>
                        )}
                        <span className="text-xs text-gray-500">
                          {formatDateTime(comment.create_time)}
                        </span>
                      </div>
                      <div
                        className="text-xs text-gray-600 ml-6 break-words prose prose-xs max-w-none prose-a:text-blue-600"
                        dangerouslySetInnerHTML={createSafeHtmlWithHighlight(comment.text, searchTerm)}
                      />

                      {/* 评论图片 */}
                      {comment.images && comment.images.length > 0 && (
                        <div className="ml-6 mt-2">
                          <ImageGallery
                            images={comment.images}
                            className="comment-images"
                            size="small"
                            groupId={groupId.toString()}
                          />
                        </div>
                      )}

                      {/* 嵌套回复评论（二级评论） */}
                      {comment.replied_comments && comment.replied_comments.length > 0 && (
                        <div className="ml-6 mt-2 space-y-2 border-l-2 border-gray-200 pl-3">
                          {comment.replied_comments.map((reply: any) => (
                            <div key={reply.comment_id} className="bg-white rounded p-2">
                              <div className="flex items-center gap-2 mb-1">
                                {reply.owner && (
                                  <img
                                    src={apiClient.getProxyImageUrl(reply.owner.avatar_url || '', groupId.toString())}
                                    alt={reply.owner.name}
                                    loading="lazy"
                                    decoding="async"
                                    className="w-3 h-3 rounded-full object-cover block"
                                    onError={(e) => {
                                      (e.currentTarget as HTMLImageElement).style.display = 'none';
                                    }}
                                  />
                                )}
                                <span className="text-xs font-medium text-gray-600">
                                  {reply.owner?.name || '未知用户'}
                                </span>
                                {reply.repliee && (
                                  <>
                                    <span className="text-xs text-gray-400">回复</span>
                                    <span className="text-xs font-medium text-blue-500">
                                      {reply.repliee.name}
                                    </span>
                                  </>
                                )}
                                <span className="text-xs text-gray-400">
                                  {formatDateTime(reply.create_time)}
                                </span>
                              </div>
                              <div
                                className="text-xs text-gray-500 ml-5 break-words prose prose-xs max-w-none prose-a:text-blue-600"
                                dangerouslySetInnerHTML={createSafeHtmlWithHighlight(reply.text || '', searchTerm)}
                              />
                              {/* 嵌套回复图片 */}
                              {reply.images && reply.images.length > 0 && (
                                <div className="ml-5 mt-1">
                                  <ImageGallery
                                    images={reply.images}
                                    className="reply-images"
                                    size="small"
                                    groupId={groupId.toString()}
                                  />
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
                    {(() => {
                      // 修复展开收起按钮逻辑
                      const isExpanded = expandedComments.has(topic.topic_id);
                      const hasMoreComments = topicDetail.show_comments.length > visibleCommentCount;
                      const shouldShowToggle = isExpanded || hasMoreComments;

                      return shouldShowToggle && (
                        <div className="text-center mt-2">
                          <button type="button"
                            onClick={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              toggleComments(topic.topic_id);
                            }}
                            className="text-xs text-blue-600 hover:text-blue-800 font-medium transition-colors"
                          >
                            {isExpanded ? '收起' : `展开全部 (${topicDetail.show_comments.length - visibleCommentCount}条)`}
                          </button>
                        </div>
                      );
                    })()}
                  </div>
              );
            })()}

            {/* 统计信息 */}
            <div className="flex items-center justify-between text-sm text-gray-500 pt-2 border-t border-gray-100">
              <div className="flex items-center gap-4">
                <span className="flex items-center gap-1">
                  <Heart className="w-4 h-4" />
                  {topic.likes_count || 0}
                </span>
                <span className="flex items-center gap-1">
                  <MessageCircle className="w-4 h-4" />
                  {topic.comments_count || 0}
                </span>
              </div>
            </div>

            {/* 点赞信息 */}
            {topicDetail?.latest_likes && topicDetail.latest_likes.length > 0 && (
              <div className="mt-2 text-xs text-gray-500">
                <span>
                  {topicDetail.latest_likes.map((like: any) => like.owner.name).join('、')}
                  {topicDetail.latest_likes.length === 1 ? ' 觉得很赞' : ' 等人觉得很赞'}
                </span>
              </div>
            )}
          </div>
        </div>
      </div>
    );
  };



  const getGradientByType = (type: string) => {
    switch (type) {
      case 'private':
        return 'from-purple-400 to-pink-500';
      case 'public':
        return 'from-blue-400 to-cyan-500';
      case 'pay':
        return 'from-orange-400 to-red-500';
      default:
        return 'from-gray-400 to-gray-600';
    }
  };

  if (loading || isRetrying) {
    return (
      <div className="min-h-screen bg-gray-50 p-4">
        <div className="max-w-4xl mx-auto">
          <div className="text-center py-8">
            <p className="text-muted-foreground">
              {isRetrying ? `正在重试获取群组信息... (第${retryCount}次)` : '加载中...'}
            </p>
            {isRetrying && (
              <p className="text-xs text-gray-400 mt-2">
                检测到API防护机制，正在自动重试获取数据
              </p>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-50 p-4">
        <div className="max-w-4xl mx-auto">
          <div className="mb-6">
            <Button
              variant="ghost"
              onClick={() => router.push('/')}
              className="flex items-center gap-2"
            >
              <ArrowLeft className="h-4 w-4" />
              返回群组列表
            </Button>
          </div>

          <Card className="max-w-md mx-auto border border-gray-200 shadow-none">
            <CardContent className="pt-6">
              <div className="text-center">
                <p className="text-red-600 mb-4">{error}</p>
                <Button onClick={() => loadGroupDetail()}>重试</Button>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  if (!group) {
    return (
      <div className="min-h-screen bg-gray-50 p-4">
        <div className="max-w-4xl mx-auto">
          <div className="mb-6">
            <Button
              variant="ghost"
              onClick={() => router.push('/')}
              className="flex items-center gap-2"
            >
              <ArrowLeft className="h-4 w-4" />
              返回群组列表
            </Button>
          </div>

          <Card className="max-w-md mx-auto border border-gray-200 shadow-none">
            <CardContent className="pt-6">
              <div className="text-center">
                <p className="text-muted-foreground">未找到群组信息</p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen bg-gray-50 overflow-hidden flex flex-col">
      <div className="flex-shrink-0 p-4">
        <div className="flex items-center gap-4">
          <Button
            variant="ghost"
            onClick={() => router.push('/')}
            className="flex items-center gap-2"
          >
            <ArrowLeft className="h-4 w-4" />
            返回群组列表
          </Button>

          <div className="flex items-center gap-4 flex-1 justify-center max-w-2xl mx-auto">
            {/* 专栏入口按钮 - 仅在有专栏时显示 */}
            {hasColumns && (
              <Button
                variant="outline"
                size="sm"
                className="flex items-center gap-2 whitespace-nowrap bg-gradient-to-r from-amber-50 to-orange-50 border-amber-200 hover:border-amber-300 hover:from-amber-100 hover:to-orange-100 text-amber-700"
                onClick={() => router.push(`/groups/${groupId}/columns`)}
              >
                <BookOpen className="h-4 w-4" />
                {columnsTitle || '专栏'}
              </Button>
            )}
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 h-4 w-4" />
              <Input
                placeholder="搜索话题..."
                value={searchTerm}
                onChange={(e) => {
                  setSearchTerm(e.target.value);
                  setCurrentPage(1);
                }}
                className="pl-10"
              />
            </div>
            <Button onClick={() => loadTopics()} disabled={topicsLoading}>
              {topicsLoading ? '加载中...' : '刷新'}
            </Button>
          </div>

        </div>
      </div>

      {/* 三列布局改为两列布局 - 使用flex布局，左右固定，中间滚动 */}
      <div className="flex-1 flex gap-4 px-4 pb-4 min-h-0">
        
        {/* 左侧：社群信息 - 固定宽度，使用sticky定位 */}
        <div className="w-80 flex-shrink-0 sticky top-0 h-fit max-h-screen">
          <Card className="border border-gray-200 shadow-none h-full">
            <ScrollArea className="h-full">
              <CardContent className="p-4 flex flex-col">
                <div className="flex items-center gap-3 mb-4">
                  <SafeImage
                    src={group.background_url}
                    alt={group.name}
                    className="w-12 h-12 rounded-lg object-cover"
                    fallbackClassName="w-12 h-12 rounded-lg"
                    fallbackText={group.name.slice(0, 2)}
                    fallbackGradient={getGradientByType(group.type)}
                  />
                  <div className="flex-1">
                    <h2 className="text-lg font-bold text-gray-900 mb-1">{group.name}</h2>
                    <div className="flex items-center gap-2">
                      {getTypeBadge(group.type)}
                      {getStatusBadge(group.status)}
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-3 text-sm">
                  {group.join_time && (
                    <div>
                      <span className="text-gray-500 block">加入时间</span>
                      <span className="text-gray-900 font-medium">{formatDate(group.join_time)}</span>
                    </div>
                  )}
                  {group.expiry_time && (
                    <div>
                      <span className="text-gray-500 block">到期时间</span>
                      <span className={
                        group.status === 'expiring_soon' ? 'text-yellow-600 font-medium' :
                        group.status === 'expired' ? 'text-red-600 font-medium' : 'text-gray-900 font-medium'
                      }>
                        {formatDate(group.expiry_time)}
                      </span>
                    </div>
                  )}
                  {groupStats && (
                    <div>
                      <span className="text-gray-500 block">本地话题数</span>
                      <span className="text-blue-600 font-semibold">{groupStats.topics_count}</span>
                    </div>
                  )}
                </div>

                
              </CardContent>
            </ScrollArea>
          </Card>
        </div>

        {/* 中间：话题和日志 - 可滚动区域 */}
        <div className="flex-1 flex flex-col min-w-0 min-h-0">
          <Tabs value={activeTab} onValueChange={setActiveTab} className="flex flex-col h-full">
            {/* 固定的标签页头部 */}
            <div className="flex-shrink-0 mb-4">
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="topics" className="flex items-center gap-2">
                  <MessageSquare className="h-4 w-4" />
                  话题列表
                </TabsTrigger>
                <TabsTrigger value="logs" className="flex items-center gap-2">
                  <FileText className="h-4 w-4" />
                  任务日志
                </TabsTrigger>
              </TabsList>
            </div>

            {/* 话题内容区域 */}
            <TabsContent value="topics" className="flex-1 flex flex-col min-h-0">
              {/* 可滚动的话题列表区域 */}
              <div className="flex-1 flex flex-col min-h-0">
                {topicsLoading ? (
                  <div className="flex-1 flex items-center justify-center">
                    <p className="text-muted-foreground">加载中...</p>
                  </div>
                ) : topics.length === 0 ? (
                  <div className="flex-1 flex items-center justify-center">
                    <p className="text-muted-foreground">
                      {searchTerm ? '没有找到匹配的话题' : '暂无话题数据，请先进行数据采集'}
                    </p>
                  </div>
                ) : (
                  <>
                    {/* 使用ScrollArea组件实现美化的滚动条 */}
                    <ScrollArea ref={scrollAreaRef} className="flex-1 w-full">
                      <div className="topic-cards-container space-y-3 pr-4 max-w-full" style={{width: '100%', maxWidth: '100%', boxSizing: 'border-box'}}>
                        {topics.map((topic: any) => (
                          <div key={topic.topic_id} style={{width: '100%', maxWidth: '100%', boxSizing: 'border-box'}}>
                            <TopicCard
                              topic={topic}
                              searchTerm={searchTerm}
                              // 这里同样使用字符串形式的 topic_id 作为索引
                              topicDetail={topicDetails.get(String((topic as any).topic_id || ''))}
                            />
                          </div>
                        ))}
                      </div>
                    </ScrollArea>

                    {/* 固定的分页控件 */}
                    {totalPages > 1 && (
                      <div className="flex-shrink-0 flex items-center justify-center gap-3 pt-4 border-t border-gray-200 mt-4">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setCurrentPage(Math.max(1, currentPage - 1))}
                          disabled={currentPage === 1}
                        >
                          上一页
                        </Button>

                        <div className="flex items-center gap-2">
                          <span className="text-sm text-gray-600">第</span>
                          <input
                            type="number"
                            min="1"
                            max={totalPages}
                            defaultValue={currentPage}
                            key={currentPage} // 强制重新渲染以更新defaultValue
                            onChange={(e) => {
                              // 允许用户自由输入，不进行页面跳转
                              // 页面跳转只在Enter键或失焦时触发
                            }}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                const value = e.currentTarget.value;
                                if (value === '') {
                                  return;
                                }
                                const page = parseInt(value);
                                if (!isNaN(page) && page >= 1 && page <= totalPages) {
                                  setCurrentPage(page);
                                }
                              }
                            }}
                            onBlur={(e) => {
                              const value = e.target.value;
                              // 失去焦点时进行页面跳转或恢复
                              if (value === '' || isNaN(parseInt(value))) {
                                // 输入为空或无效，恢复到当前页
                                e.target.value = currentPage.toString();
                              } else {
                                const page = parseInt(value);
                                if (page >= 1 && page <= totalPages) {
                                  // 有效页面，进行跳转
                                  setCurrentPage(page);
                                } else {
                                  // 超出范围，恢复到当前页
                                  e.target.value = currentPage.toString();
                                }
                              }
                            }}
                            className="w-16 px-2 py-1 text-sm text-center border border-gray-300 rounded focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                          />
                          <span className="text-sm text-gray-600">页，共 {totalPages} 页</span>
                        </div>

                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setCurrentPage(Math.min(totalPages, currentPage + 1))}
                          disabled={currentPage === totalPages}
                        >
                          下一页
                        </Button>
                      </div>
                    )}
                  </>
                )}
              </div>
            </TabsContent>

            {/* 任务日志区域 */}
            <TabsContent value="logs" className="flex-1 flex flex-col min-h-0">
              <div className="flex-1 min-h-0">
                <div className="h-full bg-gradient-to-br from-slate-50 to-gray-100 rounded-lg border border-gray-200 overflow-hidden">
                  <TaskLogViewer
                    taskId={currentTaskId}
                    onClose={() => setCurrentTaskId(null)}
                    inline={true}
                    onTaskStop={() => {
                      setTimeout(() => {
                        loadGroupStats();
                        loadTopics();
                        loadRecentTasks();
                      }, 1000);
                    }}
                  />
                </div>
              </div>
            </TabsContent>
          </Tabs>
        </div>
      </div>

      </div>
  );
}
