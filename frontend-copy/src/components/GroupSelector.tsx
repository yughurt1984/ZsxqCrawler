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
import { MessageSquare, Crown, UserPlus, LogOut, RefreshCw, Trash2, User, CreditCard, Settings, FileText } from 'lucide-react';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { apiClient, Group, GroupStats, AccountSelf } from '@/lib/api';
import { toast } from 'sonner';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog';
import SafeImage from './SafeImage';
import AuthDialog from './AuthDialog';
import '../styles/group-selector.css';

// access_mode 配置（中文 + 样式）
const getAccessModeConfig = (mode: string) => {
  const configs: Record<string, { label: string; className: string }> = {
    'admin': {
      label: '管理员',
      className: 'bg-purple-100 text-purple-700 border-purple-300'
    },
    'vip': {
      label: 'VIP会员',
      className: 'bg-amber-100 text-amber-700 border-amber-300'
    },
    'client': {
      label: '付费客户',
      className: 'bg-blue-100 text-blue-700 border-blue-300'
    },
    'free': {
      label: '免费用户',
      className: 'bg-gray-100 text-gray-700 border-gray-300'
    }
  };
  return configs[mode] || { label: mode, className: 'bg-gray-100 text-gray-700 border-gray-300' };
};


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
  const [currentUser, setCurrentUser] = useState<{ id: number; username: string; access_mode: string; allowed_groups: Record<number, { expiry: string; joined: string }> } | null>(null);
  const [groupProducts, setGroupProducts] = useState<Record<number, any>>({});  // 添加这一行


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

      // 1. 先加载商品数据
      let productsMap: Record<number, any> = {};
      try {
        const response = await fetch('http://localhost:8209/api/groups/products');
        const data = await response.json();
        data.products.forEach((p: any) => {
          productsMap[p.group_id] = p;
        });
        setGroupProducts(productsMap);
      } catch (e) {
        console.warn('加载商品数据失败:', e);
      }

      // 2. 加载群组数据
      const data = await apiClient.getGroups();

      // 3. 过滤：只显示有商品的群组
      const filteredGroups = data.groups.filter((group: Group) => 
        productsMap.hasOwnProperty(group.group_id)
      );

      setGroups(filteredGroups);

      // 并发拉取每个群组的所属账号用户信息（头像/昵称等）
      try {
        const selfPromises = filteredGroups.map(async (group: Group) => {
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
      const statsPromises = filteredGroups.map(async (group: Group) => {
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

    // 新增：退出登录
  const handleLogout = () => {
    apiClient.clearToken();
    setCurrentUser(null);
    setAuthOpen(true);
  };


  // 获取授权状态（包含文字和颜色）
  const getExpiryStatus = (expiryTime?: string): { text: string; colorClass: string } => {
    if (!expiryTime) {
      return { text: '免费', colorClass: 'bg-gray-100 text-gray-700' };
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

    // 当天到期
    if (diffDays === 0) {
      return { text: '当天到期', colorClass: 'bg-yellow-100 text-yellow-700 hover:bg-yellow-200' };
    }

    // 7天内到期
    if (diffDays <= 7) {
      return { text: `${diffDays}天后到期`, colorClass: 'bg-yellow-100 text-yellow-700 hover:bg-yellow-200' };
    }

    // 未到期（超过7天）
    return { text: '未到期', colorClass: 'bg-green-100 text-green-700 hover:bg-green-200' };
  };

  // 获取群组卡片的访问类型标签
  const getGroupAccessTypeBadge = (groupId: number) => {
    if (!currentUser) return <Badge className="bg-gray-100 text-gray-700 text-xs px-1.5 py-0.5">免费</Badge>;

    switch (currentUser.access_mode) {
      case 'admin':
        return <Badge className="bg-purple-100 text-purple-700 text-xs px-1.5 py-0.5">管理员</Badge>;
      case 'vip':
        return <Badge className="bg-amber-100 text-amber-700 text-xs px-1.5 py-0.5">VIP</Badge>;
      case 'client':
        // 检查是否被授权访问该群组
        if (currentUser.allowed_groups && groupId in currentUser.allowed_groups) {
          return <Badge className="bg-green-100 text-green-700 text-xs px-1.5 py-0.5">已订阅</Badge>;
        }
        return <Badge className="bg-gray-100 text-gray-700 text-xs px-1.5 py-0.5">免费</Badge>;
      case 'free':
      default:
        return <Badge className="bg-gray-100 text-gray-700 text-xs px-1.5 py-0.5">免费</Badge>;
    }
  };

  // 获取授权到期状态标签（仅客户用户且已授权时显示）
  const getGroupExpiryBadge = (groupId: number) => {
    if (!currentUser || currentUser.access_mode !== 'client') return null;
    if (!currentUser.allowed_groups || !(groupId in currentUser.allowed_groups)) return null;

    const status = getExpiryStatus(currentUser.allowed_groups[groupId].expiry);
    return <Badge className={`text-xs px-1.5 py-0.5 ${status.colorClass}`}>{status.text}</Badge>;
  };

  // 获取到期日期显示（仅客户用户且已授权时显示）
  const getGroupExpiryDate = (groupId: number) => {
    if (!currentUser || currentUser.access_mode !== 'client') return null;
    if (!currentUser.allowed_groups || !(groupId in currentUser.allowed_groups)) return null;

    const expiry = currentUser.allowed_groups[groupId].expiry;
    return (
      <span className="text-xs text-gray-500">
        至 {formatDate(expiry)}
      </span>
    );
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
            <div className="flex items-center justify-between gap-2">
              <div className="flex-shrink-0">
                <h1 className="text-lg sm:text-xl md:text-2xl font-bold mb-0.5 sm:mb-1 whitespace-nowrap">
                  🌟 六便士拾荒的知识库
                </h1>
                <p className="text-xs sm:text-sm text-muted-foreground whitespace-nowrap">
                  选择要操作的群组
                </p>
              </div>

              <div className="flex items-center gap-1.5 sm:gap-2 flex-shrink-0">
                {currentUser ? (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="outline"
                        className="flex items-center gap-1 sm:gap-2 h-8 sm:h-9 px-2 sm:px-3"
                      >
                        <User className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
                        <span className="text-xs sm:text-sm max-w-[60px] sm:max-w-none truncate">
                          {currentUser.username}
                        </span>
                        <span className={`px-1 sm:px-2 py-0.5 text-[10px] sm:text-xs font-medium rounded-full border ${getAccessModeConfig(currentUser.access_mode).className}`}>
                          {getAccessModeConfig(currentUser.access_mode).label}
                        </span>
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-48">
                      {/* 管理后台入口 - 仅管理员可见 */}
                      {currentUser?.access_mode === 'admin' && (
                        <DropdownMenuItem onClick={() => router.push('/admin')}>
                          <Settings className="h-4 w-4 mr-2" />
                          管理后台
                        </DropdownMenuItem>
                      )}
                      <DropdownMenuItem>
                        <CreditCard className="h-4 w-4 mr-2" />
                        订阅
                      </DropdownMenuItem>
                      <DropdownMenuItem>
                        <FileText className="h-4 w-4 mr-2" />
                        订单
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem onClick={handleLogout} className="text-red-600">
                        <LogOut className="h-4 w-4 mr-2" />
                        退出
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                ) : (
                  <Button
                    variant="outline"
                    onClick={() => setAuthOpen(true)}
                    className="flex items-center gap-1 sm:gap-2 h-8 sm:h-9 px-2 sm:px-3"
                  >
                    <UserPlus className="h-3.5 w-3.5 sm:h-4 sm:w-4" />
                    <span className="text-xs sm:text-sm">注册 / 登录</span>
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
                const product = groupProducts[group.group_id];

                return (
                  <div
                    key={group.group_id}
                    className="group-card cursor-pointer w-full sm:w-[200px]"
                    onClick={() => onGroupSelected(group)}
                  >
                    {/* 群组封面 */}
                    <div className="w-full aspect-square sm:w-[200px] sm:h-[200px]">
                      <SafeImage
                        src={(() => {
                          if (product?.cover_image) {
                            if (product.cover_image.startsWith('http')) {
                              return product.cover_image;
                            } else {
                              // 使用代理 API 解决 CORS 问题
                              const filename = product.cover_image.replace('/static/images/', '');
                              return `http://localhost:8209/api/image/${filename}`;
                            }
                          }
                          return group.background_url;
                        })()}
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
                        {product?.name || group.name}
                      </h3>
                      
                      {/* 第一行：群主信息 + 订阅类型标签 */}
                      <div className="flex items-center justify-between text-xs text-gray-500 mb-1.5">
                        {group.owner && (
                          <div className="flex items-center gap-1">
                            <Crown className="h-3 w-3" />
                            <span className="truncate max-w-[60px]">{group.owner.name}</span>
                          </div>
                        )}
                        {getGroupAccessTypeBadge(group.group_id)}
                      </div>
                      {/* 第二行：到期状态标签 + 到期日期 */}
                      <div className="flex items-center justify-between">
                        {getGroupExpiryBadge(group.group_id)}
                        {getGroupExpiryDate(group.group_id)}
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


        
