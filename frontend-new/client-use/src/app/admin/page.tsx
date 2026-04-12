/* eslint-disable @typescript-eslint/no-unused-vars */
/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable react/no-unescaped-entities */


'use client';

import { useState, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { 
  ArrowLeft, Users, Package, CreditCard, Plus, Edit, Trash2, 
  Eye, EyeOff
} from 'lucide-react';
import { apiClient } from '@/lib/api';
import { toast } from 'sonner';
import { API_BASE_URL } from '@/lib/api';
import { 
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, 
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, 
  AlertDialogTitle, AlertDialogTrigger 
} from '@/components/ui/alert-dialog';

interface User {
  id: number;
  username: string;
  email: string;
  phone: string;
  access_mode: string;
  created_at: string;
  login_count?: number;      // 新增
  last_login_at?: string;    // 新增
  last_login_ip?: string;    // 新增
}

interface GroupProduct {
  id: number;
  group_id: number;
  name: string;
  price_monthly: number;
  price_quarterly: number | null;
  price_yearly: number | null;
  original_price: number | null;
  is_visible: boolean;
  cover_image: string | null;
  created_at: string;
}

interface Subscription {
  user_id: number;
  group_id: number;
  granted_at: string;
  expire_at: string;
  subscription_type: string;
  username?: string;
  group_name?: string;
}

interface GroupedSubscription {
  user_id: number;
  username: string;
  subscriptions: Subscription[];
}

export default function AdminPage() {
  const router = useRouter();
  const [currentUser, setCurrentUser] = useState<any>(null);
  
  // 用户管理
  const [users, setUsers] = useState<User[]>([]);
  const [userSearch, setUserSearch] = useState('');
  const [usersLoading, setUsersLoading] = useState(false);
  
  // 群组商品管理
  const [products, setProducts] = useState<GroupProduct[]>([]);
  const [productsLoading, setProductsLoading] = useState(false);
  const [editingProduct, setEditingProduct] = useState<GroupProduct | null>(null);
  const [productForm, setProductForm] = useState({
    group_id: '',
    name: '',
    price_monthly: '0',
    price_quarterly: '',
    price_yearly: '',
    original_price: '',
    is_visible: true,
    cover_image: ''
  });
  
  // 图片选择
  const [showImagePicker, setShowImagePicker] = useState(false);
  const [serverImages, setServerImages] = useState<any[]>([]);
  const [loadingImages, setLoadingImages] = useState(false);


  // 订阅管理
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [subSearch, setSubSearch] = useState('');
  const [subsLoading, setSubsLoading] = useState(false);

  // 新增：订阅表单状态
  const [showSubForm, setShowSubForm] = useState(false);
  const [editingSub, setEditingSub] = useState<Subscription | null>(null);
  const [subForm, setSubForm] = useState({
    user_id: '',
    group_id: '',
    granted_at: new Date().toISOString().split('T')[0],
    expire_at: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
    subscription_type: 'monthly'
  });

  // 按用户分组订阅
  const groupedSubscriptions = useMemo(() => {
    const groups: { [key: number]: GroupedSubscription } = {};
    
    // 先过滤搜索
    const filtered = subscriptions.filter(sub => {
      const query = subSearch.toLowerCase();
      return !query || 
        sub.user_id.toString().includes(query) ||
        (sub.username || '').toLowerCase().includes(query) ||
        sub.group_id.toString().includes(query) ||
        (sub.group_name || '').toLowerCase().includes(query);
    });
    
    filtered.forEach(sub => {
      if (!groups[sub.user_id]) {
        groups[sub.user_id] = {
          user_id: sub.user_id,
          username: sub.username || `用户${sub.user_id}`,
          subscriptions: []
        };
      }
      groups[sub.user_id].subscriptions.push(sub);
    });
    
    return Object.values(groups);
  }, [subscriptions, subSearch]);

  
  // 检查管理员权限
  useEffect(() => {
    const checkAuth = async () => {
      try {
        const user = await apiClient.getMe();
        if (user.access_mode !== 'admin') {
          toast.error('无权限访问');
          router.push('/');
          return;
        }
        setCurrentUser(user);
      } catch {
        router.push('/');
      }
    };
    checkAuth();
  }, [router]);

  // 加载数据
  useEffect(() => {
    if (currentUser) {
      loadUsers();
      loadProducts();
      loadSubscriptions();
    }
  }, [currentUser]);

  // ===== 用户管理 =====
  const loadUsers = async () => {
    setUsersLoading(true);
    try {
      const res = await apiClient.request<{ users: User[] }>('/api/admin/users');
      setUsers(res.users || []);
    } catch (e) {
      console.error('加载用户失败:', e);
    } finally {
      setUsersLoading(false);
    }
  };

  const updateUserAccessMode = async (userId: number, mode: string) => {
    try {
      await apiClient.request(`/api/admin/users/${userId}/access-mode`, {
        method: 'PUT',
        body: JSON.stringify({ access_mode: mode })
      });
      toast.success('已更新用户权限');
      loadUsers();
    } catch (e) {
      toast.error('更新失败');
    }
  };

  // ===== 群组商品管理 =====
  const loadProducts = async () => {
    setProductsLoading(true);
    try {
      const res = await apiClient.request<{ products: GroupProduct[] }>('/api/admin/group-products');
      setProducts(res.products || []);
    } catch (e) {
      console.error('加载商品失败:', e);
    } finally {
      setProductsLoading(false);
    }
  };

  // 加载服务器图片列表
  const loadServerImages = async () => {
    setLoadingImages(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/admin/images`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`
        }
      });
      const data = await response.json();
      setServerImages(data.images || []);
    } catch (e) {
      toast.error('获取图片列表失败');
    } finally {
      setLoadingImages(false);
    }
  };

  // 选择服务器图片
  const selectServerImage = (imageUrl: string) => {
    setProductForm({
      ...productForm,
      cover_image: imageUrl
    });
    setShowImagePicker(false);
    toast.success('已选择图片');
  };


  const createProduct = async () => {
    // 验证必填字段
    if (!productForm.group_id || !productForm.name) {
      toast.error('请填写群组ID和群组名称');
      return;
    }

    const groupId = parseInt(productForm.group_id);
    if (isNaN(groupId)) {
      toast.error('群组ID必须是数字');
      return;
    }

    try {
      await apiClient.request('/api/admin/group-products', {
        method: 'POST',
        body: JSON.stringify({
          group_id: groupId,
          name: productForm.name.trim(),
          price_monthly: parseFloat(productForm.price_monthly) || 0,
          price_quarterly: productForm.price_quarterly ? parseFloat(productForm.price_quarterly) : null,
          price_yearly: productForm.price_yearly ? parseFloat(productForm.price_yearly) : null,
          original_price: productForm.original_price ? parseFloat(productForm.original_price) : null,
          is_visible: productForm.is_visible,
          cover_image: productForm.cover_image || null
        })
      });
      toast.success('商品创建成功');
      resetProductForm();
      loadProducts();
    } catch (e: any) {
      toast.error(e?.message || '创建失败');
    }
  };

  const updateProduct = async () => {
    if (!editingProduct) return;

    // 验证必填字段
    if (!productForm.name) {
      toast.error('请填写群组名称');
      return;
    }

    try {
      await apiClient.request(`/api/admin/group-products/${editingProduct.group_id}`, {
        method: 'PUT',
        body: JSON.stringify({
          name: productForm.name.trim(),
          price_monthly: parseFloat(productForm.price_monthly) || 0,
          price_quarterly: productForm.price_quarterly ? parseFloat(productForm.price_quarterly) : null,
          price_yearly: productForm.price_yearly ? parseFloat(productForm.price_yearly) : null,
          original_price: productForm.original_price ? parseFloat(productForm.original_price) : null,
          is_visible: productForm.is_visible,
          cover_image: productForm.cover_image || null
        })
      });
      toast.success('商品更新成功');
      resetProductForm();
      loadProducts();
    } catch (e: any) {
      toast.error(e?.message || '更新失败');
    }
  };


  const deleteProduct = async (groupId: number) => {
    try {
      await apiClient.request(`/api/admin/group-products/${groupId}`, {
        method: 'DELETE'
      });
      toast.success('商品已删除');
      loadProducts();
    } catch (e) {
      toast.error('删除失败');
    }
  };

  const toggleProductVisibility = async (product: GroupProduct) => {
    try {
      await apiClient.request(`/api/admin/group-products/${product.group_id}`, {
        method: 'PUT',
        body: JSON.stringify({ is_visible: !product.is_visible })
      });
      toast.success(product.is_visible ? '已下架' : '已上架');
      loadProducts();
    } catch (e) {
      toast.error('操作失败');
    }
  };

  const resetProductForm = () => {
    setProductForm({
      group_id: '',
      name: '',
      price_monthly: '0',
      price_quarterly: '',
      price_yearly: '',
      original_price: '',
      is_visible: true,
      cover_image: ''
    });
    setEditingProduct(null);
  };

  const startEditProduct = (product: GroupProduct) => {
    setEditingProduct(product);
    setProductForm({
      group_id: product.group_id.toString(),
      name: product.name,
      price_monthly: product.price_monthly.toString(),
      price_quarterly: product.price_quarterly?.toString() || '',
      price_yearly: product.price_yearly?.toString() || '',
      original_price: product.original_price?.toString() || '',
      is_visible: product.is_visible,
      cover_image: product.cover_image || ''
    });
  };

  // ===== 订阅管理 =====
  const loadSubscriptions = async () => {
    setSubsLoading(true);
    try {
      const res = await apiClient.request<{ subscriptions: Subscription[] }>('/api/admin/subscriptions');
      setSubscriptions(res.subscriptions || []);
    } catch (e) {
      console.error('加载订阅失败:', e);
    } finally {
      setSubsLoading(false);
    }
  };

  const updateSubscription = async (userId: number, groupId: number, expireAt: string, type: string) => {
    try {
      await apiClient.request(`/api/admin/subscriptions/${userId}/${groupId}`, {
        method: 'PUT',
        body: JSON.stringify({
          expire_at: expireAt,
          subscription_type: type
        })
      });
      toast.success('订阅已更新');
      loadSubscriptions();
    } catch (e) {
      toast.error('更新失败');
    }
  };

  const revokeSubscription = async (userId: number, groupId: number) => {
    try {
      await apiClient.request(`/api/admin/subscriptions/${userId}/${groupId}`, {
        method: 'DELETE'
      });
      toast.success('已撤销授权');
      loadSubscriptions();
    } catch (e) {
      toast.error('撤销失败');
    }
  };

  // 权限模式标签
  const getAccessModeBadge = (mode: string) => {
    switch (mode) {
      case 'admin':
        return <Badge className="bg-red-100 text-red-700">管理员</Badge>;
      case 'vip':
        return <Badge className="bg-purple-100 text-purple-700">VIP</Badge>;
      case 'client':
        return <Badge className="bg-blue-100 text-blue-700">客户</Badge>;
      default:
        return <Badge className="bg-gray-100 text-gray-700">免费用户</Badge>;
    }
  };

  if (!currentUser) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p>加载中...</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      <div className="max-w-7xl mx-auto">
        {/* 头部 */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <Button variant="ghost" onClick={() => router.push('/')}>
              <ArrowLeft className="h-4 w-4 mr-2" />
              返回首页
            </Button>
            <h1 className="text-2xl font-bold">管理后台</h1>
          </div>
          <div className="text-sm text-gray-500">
            当前用户: {currentUser.username}
          </div>
        </div>

        {/* 主内容区 */}
        <Tabs defaultValue="groups" className="space-y-4">
          <TabsList className="grid w-full grid-cols-3 max-w-md">
            <TabsTrigger value="groups" className="flex items-center gap-2">
              <Package className="h-4 w-4" />
              群组商品
            </TabsTrigger>
            <TabsTrigger value="users" className="flex items-center gap-2">
              <Users className="h-4 w-4" />
              用户管理
            </TabsTrigger>
            <TabsTrigger value="subscriptions" className="flex items-center gap-2">
              <CreditCard className="h-4 w-4" />
              订阅管理
            </TabsTrigger>
          </TabsList>

          {/* ===== 群组商品管理 ===== */}
          <TabsContent value="groups">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>群组商品管理</CardTitle>
                  <Button onClick={() => {
                    resetProductForm();
                    setEditingProduct({} as any); // 新建模式
                  }}>
                    <Plus className="h-4 w-4 mr-2" />
                    添加商品
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                {/* 商品表单 */}
                {editingProduct !== null && (
                  <div className="mb-6 p-4 bg-gray-50 rounded-lg">
                    <h3 className="font-medium mb-4">
                      {editingProduct.id ? '编辑商品' : '新建商品'}
                    </h3>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-sm text-gray-500 block mb-1">群组ID *</label>
                        <Input 
                          value={productForm.group_id}
                          onChange={(e) => setProductForm({...productForm, group_id: e.target.value})}
                          disabled={!!editingProduct.id}
                          placeholder="输入群组ID"
                        />
                      </div>
                      <div>
                        <label className="text-sm text-gray-500 block mb-1">群组名称 *</label>
                        <Input 
                          value={productForm.name}
                          onChange={(e) => setProductForm({...productForm, name: e.target.value})}
                          placeholder="输入群组名称"
                        />
                      </div>
                      
                      <div>
                        <label className="text-sm text-gray-500 block mb-1">月订阅价格</label>
                        <Input 
                          type="number"
                          value={productForm.price_monthly}
                          onChange={(e) => setProductForm({...productForm, price_monthly: e.target.value})}
                          placeholder="0.00"
                        />
                      </div>
                      <div>
                        <label className="text-sm text-gray-500 block mb-1">季订阅价格</label>
                        <Input 
                          type="number"
                          value={productForm.price_quarterly}
                          onChange={(e) => setProductForm({...productForm, price_quarterly: e.target.value})}
                          placeholder="可选"
                        />
                      </div>
                      <div>
                        <label className="text-sm text-gray-500 block mb-1">年订阅价格</label>
                        <Input 
                          type="number"
                          value={productForm.price_yearly}
                          onChange={(e) => setProductForm({...productForm, price_yearly: e.target.value})}
                          placeholder="可选"
                        />
                      </div>
                      <div>
                        <label className="text-sm text-gray-500 block mb-1">原价（划线价）</label>
                        <Input 
                          type="number"
                          value={productForm.original_price}
                          onChange={(e) => setProductForm({...productForm, original_price: e.target.value})}
                          placeholder="可选"
                        />
                      </div>
                      <div className="col-span-2">
                        <label className="text-sm text-gray-500 block mb-1">封面图片</label>
                        <div className="flex gap-2 mb-2">
                          <Input 
                            value={productForm.cover_image}
                            onChange={(e) => setProductForm({...productForm, cover_image: e.target.value})}
                            placeholder="点击选择按钮选择图片"
                            className="flex-1"
                            readOnly
                          />
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              loadServerImages();
                              setShowImagePicker(true);
                            }}
                          >
                            选择图片
                          </Button>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <input 
                          type="checkbox" 
                          checked={productForm.is_visible}
                          onChange={(e) => setProductForm({...productForm, is_visible: e.target.checked})}
                          className="rounded"
                        />
                        <label className="text-sm">展示给用户</label>
                      </div>
                    </div>
                    <div className="flex gap-2 mt-4">
                      <Button onClick={editingProduct.id ? updateProduct : createProduct}>
                        {editingProduct.id ? '更新' : '创建'}
                      </Button>
                      <Button variant="outline" onClick={resetProductForm}>取消</Button>
                    </div>
                  </div>
                )}

                {/* 商品列表 */}
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>群组ID</TableHead>
                      <TableHead>名称</TableHead>
                      <TableHead>月价</TableHead>
                      <TableHead>季价</TableHead>
                      <TableHead>年价</TableHead>
                      <TableHead>状态</TableHead>
                      <TableHead>操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {productsLoading ? (
                      <TableRow><TableCell colSpan={7} className="text-center">加载中...</TableCell></TableRow>
                    ) : products.length === 0 ? (
                      <TableRow><TableCell colSpan={7} className="text-center text-gray-500">暂无商品</TableCell></TableRow>
                    ) : (
                      products.map((product) => (
                        <TableRow key={product.id}>
                          <TableCell>{product.group_id}</TableCell>
                          <TableCell>{product.name}</TableCell>
                          <TableCell>¥{product.price_monthly}</TableCell>
                          <TableCell>{product.price_quarterly ? `¥${product.price_quarterly}` : '-'}</TableCell>
                          <TableCell>{product.price_yearly ? `¥${product.price_yearly}` : '-'}</TableCell>
                          <TableCell>
                            <Badge className={product.is_visible ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}>
                              {product.is_visible ? '上架' : '下架'}
                            </Badge>
                          </TableCell>
                          <TableCell>
                            <div className="flex items-center gap-2">
                              <Button size="sm" variant="ghost" onClick={() => startEditProduct(product)}>
                                <Edit className="h-4 w-4" />
                              </Button>
                              <Button size="sm" variant="ghost" onClick={() => toggleProductVisibility(product)}>
                                {product.is_visible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                              </Button>
                              <AlertDialog>
                                <AlertDialogTrigger asChild>
                                  <Button size="sm" variant="ghost" className="text-red-600">
                                    <Trash2 className="h-4 w-4" />
                                  </Button>
                                </AlertDialogTrigger>
                                <AlertDialogContent>
                                  <AlertDialogHeader>
                                    <AlertDialogTitle>确认删除</AlertDialogTitle>
                                    <AlertDialogDescription>
                                      确定要删除群组 "{product.name}" 的商品记录吗？
                                    </AlertDialogDescription>
                                  </AlertDialogHeader>
                                  <AlertDialogFooter>
                                    <AlertDialogCancel>取消</AlertDialogCancel>
                                    <AlertDialogAction onClick={() => deleteProduct(product.group_id)}>
                                      确认删除
                                    </AlertDialogAction>
                                  </AlertDialogFooter>
                                </AlertDialogContent>
                              </AlertDialog>
                            </div>
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </TabsContent>

          {/* ===== 用户管理 ===== */}
          <TabsContent value="users">
            <Card>
              <CardHeader>
                <CardTitle>用户管理</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="mb-4">
                  <Input 
                    placeholder="搜索用户..."
                    value={userSearch}
                    onChange={(e) => setUserSearch(e.target.value)}
                    className="max-w-sm"
                  />
                </div>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>ID</TableHead>
                      <TableHead>用户名</TableHead>
                      <TableHead>邮箱</TableHead>
                      <TableHead>手机号</TableHead>
                      <TableHead>权限</TableHead>
                      <TableHead>登录次数</TableHead>
                      <TableHead>最后登录</TableHead>
                      <TableHead>注册时间</TableHead>
                      <TableHead>操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {usersLoading ? (
                      <TableRow><TableCell colSpan={9} className="text-center">加载中...</TableCell></TableRow>
                    ) : users.filter(u =>
                      u.username.includes(userSearch) ||
                      u.email.includes(userSearch)
                    ).length === 0 ? (
                      <TableRow><TableCell colSpan={9} className="text-center text-gray-500">暂无用户</TableCell></TableRow>
                    ) : (
                      users.filter(u =>
                        u.username.includes(userSearch) ||
                        u.email.includes(userSearch)
                      ).map((user) => (
                        <TableRow key={user.id}>
                          <TableCell>{user.id}</TableCell>
                          <TableCell>{user.username}</TableCell>
                          <TableCell>{user.email}</TableCell>
                          <TableCell>{user.phone}</TableCell>
                          <TableCell>{getAccessModeBadge(user.access_mode)}</TableCell>
                          <TableCell>
                            <span className="text-sm font-medium">{user.login_count || 0}</span>
                          </TableCell>
                          <TableCell>
                            <div className="text-xs">
                              <div>{user.last_login_at ? new Date(user.last_login_at).toLocaleDateString() : '-'}</div>
                              {user.last_login_ip && (
                                <div className="text-gray-500">{user.last_login_ip}</div>
                              )}
                            </div>
                          </TableCell>
                          <TableCell>{new Date(user.created_at).toLocaleDateString()}</TableCell>
                          <TableCell>
                            <select
                              className="text-sm border rounded px-2 py-1"
                              value={user.access_mode}
                              onChange={(e) => updateUserAccessMode(user.id, e.target.value)}
                            >
                              <option value="free">免费用户</option>
                              <option value="client">客户</option>
                              <option value="vip">VIP</option>
                              <option value="admin">管理员</option>
                            </select>
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>

              </CardContent>
            </Card>
          </TabsContent>

          {/* ===== 订阅管理 ===== */}
          <TabsContent value="subscriptions">
            <Card>
              <CardHeader>
                <div className="flex items-center justify-between">
                  <CardTitle>订阅管理</CardTitle>
                  <Button onClick={() => {
                    setEditingSub(null);
                    setSubForm({ 
                      user_id: '', 
                      group_id: '', 
                      granted_at: new Date().toISOString().split('T')[0],
                      expire_at: new Date(Date.now() + 30 * 24 * 60 * 60 * 1000).toISOString().split('T')[0],
                      subscription_type: 'monthly' 
                    });

                    setShowSubForm(true);
                  }}>
                    <Plus className="h-4 w-4 mr-2" />
                    添加订阅
                  </Button>
                </div>
              </CardHeader>
              <CardContent>
                {/* 订阅表单 */}
                {showSubForm && (
                  <div className="mb-6 p-4 bg-gray-50 rounded-lg">
                    <h3 className="font-medium mb-4">
                      {editingSub ? '修改订阅' : '添加订阅'}
                    </h3>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="text-sm text-gray-500 block mb-1">用户ID *</label>
                        <Input
                          value={subForm.user_id}
                          onChange={(e) => setSubForm({ ...subForm, user_id: e.target.value })}
                          disabled={!!editingSub}
                          placeholder="输入用户ID"
                          type="number"
                        />
                      </div>
                      <div>
                        <label className="text-sm text-gray-500 block mb-1">登录名</label>
                        <div className="px-3 py-2 border rounded bg-gray-100 text-gray-600 h-10 flex items-center">
                          {subForm.user_id
                            ? (users.find(u => u.id === parseInt(subForm.user_id))?.username || '未找到用户')
                            : '-'}
                        </div>
                      </div>
                      <div>
                        <label className="text-sm text-gray-500 block mb-1">群组ID *</label>
                        <Input
                          value={subForm.group_id}
                          onChange={(e) => setSubForm({ ...subForm, group_id: e.target.value })}
                          disabled={!!editingSub}
                          placeholder="输入群组ID"
                          type="number"
                        />
                      </div>
                      <div>
                        <label className="text-sm text-gray-500 block mb-1">订阅类型</label>
                        <select
                          className="w-full px-3 py-2 border rounded"
                          value={subForm.subscription_type}
                          onChange={(e) => setSubForm({ ...subForm, subscription_type: e.target.value })}
                        >
                          <option value="monthly">月订阅</option>
                          <option value="quarterly">季订阅</option>
                          <option value="yearly">年订阅</option>
                        </select>
                      </div>
                      <div>
                        <label className="text-sm text-gray-500 block mb-1">授权时间</label>
                        <Input
                          type="date"
                          value={subForm.granted_at}
                          onChange={(e) => setSubForm({ ...subForm, granted_at: e.target.value })}
                        />
                      </div>
                      <div>
                        <label className="text-sm text-gray-500 block mb-1">到期时间</label>
                        <Input
                          type="date"
                          value={subForm.expire_at}
                          onChange={(e) => setSubForm({ ...subForm, expire_at: e.target.value })}
                        />
                      </div>
                    </div>

                    <div className="flex gap-2 mt-4">
                      <Button onClick={async () => {
                        if (editingSub) {
                          // 修改订阅
                          await updateSubscription(
                            parseInt(subForm.user_id),
                            parseInt(subForm.group_id),
                            subForm.expire_at,
                            subForm.subscription_type
                          );
                        } else {
                          // 添加订阅
                          try {
                            await apiClient.request('/api/admin/grant-subscription', {
                              method: 'POST',
                              body: JSON.stringify({
                                user_id: parseInt(subForm.user_id),
                                group_id: parseInt(subForm.group_id),
                                expire_at: subForm.expire_at,
                                granted_at: subForm.granted_at,
                                subscription_type: subForm.subscription_type
                              })
                            });
                            toast.success('授权成功');
                            loadSubscriptions();
                          } catch (e) {
                            toast.error('授权失败');
                          }
                        }
                        setShowSubForm(false);
                      }}>
                        {editingSub ? '更新' : '确定'}
                      </Button>
                      <Button variant="outline" onClick={() => {
                        setShowSubForm(false)
                        setEditingSub(null);  // ⭐ 添加这行：重置编辑状态
                      }}>取消</Button>
                    </div>

                  </div>
                )}

                {/* 搜索框 */}
                <div className="mb-4">
                  <Input
                    placeholder="搜索订阅..."
                    value={subSearch}
                    onChange={(e) => setSubSearch(e.target.value)}
                    className="max-w-sm"
                  />
                </div>

                {/* 订阅列表 */}
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-20">用户ID</TableHead>
                      <TableHead className="w-24">用户名</TableHead>
                      <TableHead className="w-20">群组ID</TableHead>
                      <TableHead className="w-28">群组名称</TableHead>
                      <TableHead className="w-24">订阅类型</TableHead>
                      <TableHead className="w-28">授权时间</TableHead>
                      <TableHead className="w-28">到期时间</TableHead>
                      <TableHead className="w-20">状态</TableHead>
                      <TableHead className="w-24">操作</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {subsLoading ? (
                      <TableRow><TableCell colSpan={9} className="text-center py-4">加载中...</TableCell></TableRow>
                    ) : groupedSubscriptions.length === 0 ? (
                      <TableRow><TableCell colSpan={9} className="text-center py-4 text-gray-500">暂无订阅记录</TableCell></TableRow>
                    ) : (
                      groupedSubscriptions.map((group) => (
                        group.subscriptions.map((sub, idx) => {
                          const isExpired = new Date(sub.expire_at) < new Date();
                          const isFirst = idx === 0;
                          return (
                            <TableRow key={`${group.user_id}-${sub.group_id}`} className="border-b">
                              {isFirst && (
                                <>
                                  <TableCell rowSpan={group.subscriptions.length} className="align-middle font-medium">
                                    {group.user_id}
                                  </TableCell>
                                  <TableCell rowSpan={group.subscriptions.length} className="align-middle">
                                    {group.username}
                                  </TableCell>
                                </>
                              )}
                              <TableCell>{sub.group_id}</TableCell>
                              <TableCell>{sub.group_name || '-'}</TableCell>
                              <TableCell>
                                <Badge variant="outline">{sub.subscription_type}</Badge>
                              </TableCell>
                              <TableCell>{new Date(sub.granted_at).toLocaleDateString()}</TableCell>
                              <TableCell>{new Date(sub.expire_at).toLocaleDateString()}</TableCell>
                              <TableCell>
                                {isExpired ? (
                                  <Badge className="bg-red-100 text-red-700">已过期</Badge>
                                ) : (
                                  <Badge className="bg-green-100 text-green-700">有效</Badge>
                                )}
                              </TableCell>
                              <TableCell>
                                <div className="flex items-center gap-1">
                                  <Button
                                    size="sm"
                                    variant="ghost"
                                    onClick={() => {
                                      setEditingSub(sub);
                                      setSubForm({
                                        user_id: sub.user_id.toString(),
                                        group_id: sub.group_id.toString(),
                                        granted_at: sub.granted_at.split('T')[0],
                                        expire_at: sub.expire_at.split('T')[0],
                                        subscription_type: sub.subscription_type
                                      });
                                      setShowSubForm(true);
                                    }}
                                  >
                                    <Edit className="h-4 w-4" />
                                  </Button>
                                  <AlertDialog>
                                    <AlertDialogTrigger asChild>
                                      <Button size="sm" variant="ghost" className="text-red-600">
                                        <Trash2 className="h-4 w-4" />
                                      </Button>
                                    </AlertDialogTrigger>
                                    <AlertDialogContent>
                                      <AlertDialogHeader>
                                        <AlertDialogTitle>确认撤销</AlertDialogTitle>
                                        <AlertDialogDescription>
                                          确定要撤销该用户对群组「{sub.group_name || sub.group_id}」的访问权限吗？
                                        </AlertDialogDescription>
                                      </AlertDialogHeader>
                                      <AlertDialogFooter>
                                        <AlertDialogCancel>取消</AlertDialogCancel>
                                        <AlertDialogAction onClick={() => revokeSubscription(sub.user_id, sub.group_id)}>
                                          确认撤销
                                        </AlertDialogAction>
                                      </AlertDialogFooter>
                                    </AlertDialogContent>
                                  </AlertDialog>
                                </div>
                              </TableCell>
                            </TableRow>
                          );
                        })
                      ))
                    )}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          </TabsContent>
          
                    
        </Tabs>
        {/* 图片选择对话框 */}
        {showImagePicker && (
          <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
            <div className="bg-white rounded-lg p-6 max-w-4xl max-h-[80vh] overflow-auto">
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-lg font-semibold">选择服务器图片</h3>
                <Button variant="ghost" size="sm" onClick={() => setShowImagePicker(false)}>
                  ✕
                </Button>
              </div>

              {loadingImages ? (
                <div className="text-center py-8">加载中...</div>
              ) : serverImages.length === 0 ? (
                <div className="text-center py-8 text-gray-500">
                  <p>服务器暂无图片</p>
                  <p className="text-sm mt-2">请将图片文件放入服务器 images/ 目录</p>
                </div>
              ) : (
                <>
                  <div className="mb-2 text-sm text-gray-500">
                    共 {serverImages.length} 张图片
                  </div>
                  <div className="grid grid-cols-4 gap-4">
                    {serverImages.map((img, idx) => (
                      <div
                        key={idx}
                        className="cursor-pointer border rounded-lg overflow-hidden hover:border-blue-500 hover:shadow-lg transition-all"
                        onClick={() => selectServerImage(img.url)}
                      >
                        <img
                          src={`${API_BASE_URL}${img.url}`}
                          alt={img.filename}
                          className="w-full h-32 object-cover"
                        />
                        <div className="p-2">
                          <div className="text-xs text-gray-700 truncate font-medium">
                            {img.filename}
                          </div>
                          <div className="text-xs text-gray-400 mt-1">
                            {(img.size / 1024).toFixed(1)} KB
                          </div>
                          <div className="text-xs text-gray-400">
                            {img.created_at}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>
        )}
      </div>
      </div >
    );
  }
