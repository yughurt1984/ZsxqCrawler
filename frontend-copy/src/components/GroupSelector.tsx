// 在文件顶部添加
/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-unused-vars */

'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { MessageSquare, Crown, UserPlus, LogOut, RefreshCw, Trash2 } from 'lucide-react';
import { apiClient, Group, GroupStats, AccountSelf } from '@/lib/api';
import { toast } from 'sonner';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog';
import SafeImage from './SafeImage';
import AuthDialog from './AuthDialog';
import '../styles/group-selector.css';

interface GroupSelectorProps {
  onGroupSelected: (group: Group) => void;
}

export default function GroupSelector({ onGroupSelected }: GroupSelectorProps) {
  const router = useRouter();
  const [groups, setGroups] = useState<Group[]>([]);
  const [groupStats, setGroupStats] = useState<Record<number, GroupStats>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryCount, setRetryCount] = useState(0);
  const [isRetrying, setIsRetrying] = useState(false);
  const [accountSelfMap, setAccountSelfMap] = useState<Record<number, AccountSelf | null>>({});
  const [deletingGroups, setDeletingGroups] = useState<Set<number>>(new Set());
  const [authOpen, setAuthOpen] = useState(false);
  const [currentUser, setCurrentUser] = useState<{ id: number; username: string; access_mode: string; allowed_groups: Record<number, string> } | null>(null);



  useEffect(() => {
  if (currentUser) {
    loadGroups();
  }
}, [currentUser]);

  // 检查登录状态
  useEffect(() => {
    const checkAuth = async () => {
      const token = (apiClient as any).getToken?.();
      if (!token) {
        setAuthOpen(true);
        return;
      }
      try {
        const user = await apiClient.getMe();
        setCurrentUser({ id: user.id, username: user.username, access_mode: user.access_mode, allowed_groups: user.allowed_groups });

      } catch {
        setAuthOpen(true);
      }
    };
    checkAuth();
  }, []);

  // 监听 Token 过期
  useEffect(() => {
    const handler = () => setAuthOpen(true);
    window.addEventListener('auth-expired', handler);
    return () => window.removeEventListener('auth-expired', handler);
  }, []);


  // 监听页面可见性变化和窗口焦点，返回页面时自动刷新群组列表
  // 使用节流避免频繁刷新
  useEffect(() => {
    let lastRefresh = 0;
    const REFRESH_INTERVAL = 5000; // 最少间隔 5 秒

    const maybeRefresh = () => {
      const now = Date.now();
      if (now - lastRefresh > REFRESH_INTERVAL) {
        lastRefresh = now;
        loadGroups(0);
      }
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        maybeRefresh();
      }
    };
    const handleFocus = () => {
      maybeRefresh();
    };
    document.addEventListener('visibilitychange', handleVisibilityChange);
    window.addEventListener('focus', handleFocus);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      window.removeEventListener('focus', handleFocus);
    };
  }, []);

  const loadGroups = async (currentRetryCount = 0) => {
    // 未登录时不加载
    if (!currentUser) return;
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

      const data = await apiClient.getGroups();

      // 检查返回数据（允许为空，显示空态，不再抛错）

      setGroups(data.groups);

      // 并发拉取每个群组的所属账号用户信息（头像/昵称等）
      try {
        const selfPromises = data.groups.map(async (group: Group) => {
          try {
            const res = await apiClient.getGroupAccountSelf(group.group_id);
            return { groupId: group.group_id, self: (res as any)?.self || null };
          } catch {
            return { groupId: group.group_id, self: null };
          }
        });
        const selfResults = await Promise.all(selfPromises);
        const selfMap: Record<number, AccountSelf | null> = {};
        selfResults.forEach(({ groupId, self }) => {
          selfMap[groupId] = self;
        });
        setAccountSelfMap(selfMap);
      } catch (e) {
        // 忽略单独失败
        console.warn('加载群组账号用户信息失败:', e);
      }

      // 加载每个群组的统计信息
      const statsPromises = data.groups.map(async (group: Group) => {
        try {
          const stats = await apiClient.getGroupStats(group.group_id);
          return { groupId: group.group_id, stats };
        } catch (error) {
          console.warn(`获取群组 ${group.group_id} 统计信息失败:`, error);
          return { groupId: group.group_id, stats: null };
        }
      });

      const statsResults = await Promise.all(statsPromises);
      const statsMap: Record<number, GroupStats> = {};
      statsResults.forEach(({ groupId, stats }) => {
        if (stats) {
          statsMap[groupId] = stats;
        }
      });
      setGroupStats(statsMap);

      // 成功获取数据，重置状态
      setError(null);
      setRetryCount(0);
      setIsRetrying(false);
      setLoading(false);

    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : '加载群组列表失败';

      // 如果是API保护机制导致的错误，持续重试
      if (errorMessage.includes('未知错误') || errorMessage.includes('空数据') || errorMessage.includes('反爬虫')) {
        const nextRetryCount = currentRetryCount + 1;
        const delay = Math.min(1000 + (nextRetryCount * 500), 5000); // 递增延迟，最大5秒

        console.log(`群组列表加载失败，正在重试 (第${nextRetryCount}次)...`);

        setTimeout(() => {
          loadGroups(nextRetryCount);
        }, delay);
        return;
      }

      // 其他错误，停止重试
      setError(errorMessage);
      setIsRetrying(false);
      setLoading(false);
    }
  };



  const handleRefresh = async () => {
    try {
      await apiClient.refreshLocalGroups();
      await loadGroups(0);
      toast.success('已刷新本地群目录');
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`刷新失败: ${msg}`);
    }
  };

  const handleDeleteGroup = async (groupId: number) => {
    if (deletingGroups.has(groupId)) return;
    setDeletingGroups((prev) => new Set(prev).add(groupId));
    try {
      const res = await apiClient.deleteGroup(groupId);
      const msg = (res as any)?.message || '已删除';
      toast.success(msg);
      await loadGroups(0);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`删除失败: ${msg}`);
    } finally {
      setDeletingGroups((prev) => {
        const s = new Set(prev);
        s.delete(groupId);
        return s;
      });
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

  const getGradientByType = (type: string) => {
    switch (type) {
      case 'private':
        return 'from-purple-400 to-pink-500';
      case 'public':
        return 'from-blue-400 to-cyan-500';
      default:
        return 'from-gray-400 to-gray-600';
    }
  };

  // 新增：推出登录
  const handleLogout = () => {
    (apiClient as any).logout();
    setCurrentUser(null);
    setAuthOpen(true);
  };


  // 获取授权状态（包含文字和颜色）
  const getExpiryStatus = (expiryTime?: string): { text: string; colorClass: string } => {
    if (!expiryTime) {
      return { text: '未授权', colorClass: 'bg-gray-100 text-gray-700' };
    }

    const expiryDate = new Date(expiryTime);
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    expiryDate.setHours(0, 0, 0, 0);

    // 计算剩余天数
    const diffTime = expiryDate.getTime() - today.getTime();
    const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

    // 已过期
    if (diffDays < 0) {
      return { text: '已过期', colorClass: 'bg-red-100 text-red-700 hover:bg-red-200' };
    }

    // 今日到期
    if (diffDays === 0) {
      return { text: '今日到期', colorClass: 'bg-yellow-100 text-yellow-700 hover:bg-yellow-200' };
    }

    // 10天内到期
    if (diffDays <= 10) {
      return { text: `${diffDays}天后到期`, colorClass: 'bg-yellow-100 text-yellow-700 hover:bg-yellow-200' };
    }

    // 未到期（超过10天）
    return { text: '未到期', colorClass: 'bg-green-100 text-green-700 hover:bg-green-200' };
  };



  if (loading || isRetrying) {
    return (
      <div className="min-h-screen bg-background">
        <div className="container mx-auto p-4">
          <div className="mb-4">
            <h1 className="text-2xl font-bold mb-1">🌟 六便士拾荒的知识库</h1>
            <p className="text-sm text-muted-foreground">
              {isRetrying ? '正在重试获取群组列表...' : '正在加载您的群组...'}
            </p>
          </div>
          <div className="flex items-center justify-center py-8">
            <div className="text-center">
              <Progress value={undefined} className="w-64 mb-4" />
              <p className="text-muted-foreground">
                {isRetrying ? `正在重试... (第${retryCount}次)` : '加载群组列表中...'}
              </p>
              {isRetrying && (
                <p className="text-xs text-gray-400 mt-2">
                  检测到API防护机制，正在自动重试获取数据
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-background">
        <div className="container mx-auto p-4">
          <div className="mb-4">
            <h1 className="text-2xl font-bold mb-1">🌟 六便士拾荒的知识库</h1>
            <p className="text-sm text-muted-foreground">
              加载群组列表时出现错误
            </p>
          </div>
          <Card className="max-w-md mx-auto">
            <CardHeader>
              <CardTitle className="text-red-600">加载失败</CardTitle>
              <CardDescription>无法获取群组列表</CardDescription>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground mb-4">{error}</p>
              <Button onClick={() =>loadGroups} className="w-full">
                重试
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  // 删除网络群组（账号），保留本地群组
  
  const localGroups = groups
  .filter((g) => g.source && g.source.includes('local'))
  .filter((g) => {
  if (!currentUser) return false;
  // 所有用户都可以查看所有群组
  return true;
});


    return (
    <>
      <div className="min-h-screen bg-background">
        <div className="container mx-auto p-4">
          <div className="mb-4">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-2xl font-bold mb-1">🌟 六便士拾荒的知识库</h1>
                <p className="text-sm text-muted-foreground">
                  选择要操作的知识星球群组
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  onClick={handleRefresh}
                  className="flex items-center gap-2"
                >
                  <RefreshCw className="h-4 w-4" />
                  预留控件
                </Button>
                {currentUser ? (
                  <>
                    <span className="text-sm text-muted-foreground">{currentUser.username}</span>
                    <Button variant="outline" onClick={handleLogout} className="flex items-center gap-2">
                      <LogOut className="h-4 w-4" />
                      退出
                    </Button>
                  </>
                ) : (
                  <Button variant="outline" onClick={() => setAuthOpen(true)} className="flex items-center gap-2">
                    <UserPlus className="h-4 w-4" />
                    注册 / 登录
                  </Button>
                )}
              </div>
            </div>
          </div>

          {/* 群组统计 */}
          <div className="mb-4 space-y-0.5">
            <p className="text-sm text-muted-foreground">
              共 {localGroups.length} 个群组
            </p>
          </div>

          {/* 群组网格 - 只显示本地群组 */}
          {localGroups.length === 0 ? (
            <Card className="max-w-md mx-auto border border-gray-200 shadow-none">
              <CardContent className="pt-6">
                <div className="text-center">
                  <p className="text-muted-foreground">
                    暂无群组数据
                  </p>
                </div>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 xl:grid-cols-6 gap-4">
              {localGroups.map((group) => {
                const stats = groupStats[group.group_id];
                return (
                  <div
                    key={group.group_id}
                    className="group-card cursor-pointer bg-white border border-gray-200 rounded-lg hover:border-gray-300 transition-all duration-200 hover:shadow-md overflow-hidden w-[200px]"
                    onClick={() => onGroupSelected(group)}
                  >
                    {/* 群组封面 */}
                    <div className="w-[200px] h-[200px]">
                      <SafeImage
                        src={group.background_url}
                        alt={group.name}
                        className="w-full h-full object-cover"
                        fallbackClassName="w-full h-full bg-gradient-to-br"
                        fallbackText={group.name.slice(0, 2)}
                        fallbackGradient={getGradientByType(group.type)}
                      />
                    </div>

                    {/* 内容区域 */}
                    <div className="p-2.5">
                      <h3 className="text-sm font-semibold text-gray-900 line-clamp-1 mb-1.5">
                        {group.name}
                      </h3>
                      <div className="flex items-center justify-between text-xs text-gray-500 mb-1.5">
                        {group.owner && (
                          <div className="flex items-center gap-1">
                            <Crown className="h-3 w-3" />
                            <span className="truncate max-w-[60px]">{group.owner.name}</span>
                          </div>
                        )}
                        {stats && (
                          <div className="flex items-center gap-1">
                            <MessageSquare className="h-3 w-3" />
                            <span>{stats.topics_count || 0}</span>
                          </div>
                        )}
                      </div>
                      <div className="flex items-center justify-between">
                      {/* 付费类型 Badge */}
                      <Badge 
                        variant={currentUser?.access_mode === 'vip' ? 'default' : 
                                currentUser?.access_mode === 'paid' && currentUser.allowed_groups[group.group_id] ? 'default' : 
                                'secondary'}
                        className={`text-xs px-1.5 py-0 h-5 ${
                          currentUser?.access_mode === 'vip' ? 'bg-purple-100 text-purple-700 hover:bg-purple-200' :
                          currentUser?.access_mode === 'paid' && currentUser.allowed_groups[group.group_id]? 'bg-blue-100 text-blue-700 hover:bg-blue-200' :
                          'bg-gray-100 text-gray-700'
                        }`}
                      >
                        {currentUser?.access_mode === 'vip' ? 'VIP' :
                        currentUser?.access_mode === 'paid' ? 
                          (currentUser.allowed_groups[group.group_id] ? '付费' : '免费') :
                        '免费'}
                      </Badge>
                      
                      {/* 授权状态 Badge - 仅 paid 用户显示 */}
                      {currentUser?.access_mode === 'paid' && currentUser.allowed_groups[group.group_id] && (
                        <Badge 
                          variant="secondary"
                          className={`text-xs px-1.5 py-0 h-5 ${
                            getExpiryStatus(currentUser.allowed_groups[group.group_id]).colorClass
                          }`}
                        >
                          {getExpiryStatus(currentUser.allowed_groups[group.group_id]).text}
                        </Badge>
                      )}
                      
                      {/* 到期时间显示 - 仅 paid 用户且已授权时显示 */}
                      {currentUser?.access_mode === 'paid' && currentUser.allowed_groups[group.group_id] && (
                        <span className="text-xs text-gray-500">
                          至 {formatDate(currentUser.allowed_groups[group.group_id])}
                        </span>
                      )}      
                      </div>

                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
      
      <AuthDialog
        open={authOpen}
        onOpenChange={setAuthOpen}
        onAuthSuccess={async () => {
          try {
            const user = await apiClient.getMe();
            setCurrentUser({ id: user.id, username: user.username, access_mode: user.access_mode, allowed_groups: user.allowed_groups });
          } catch { /* ignore */ }
        }}
      />
    </>
  );
}


        
