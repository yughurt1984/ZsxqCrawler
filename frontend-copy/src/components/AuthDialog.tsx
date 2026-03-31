'use client';

import { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { apiClient } from '@/lib/api';
import { toast } from 'sonner';

interface AuthDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAuthSuccess?: () => void;
}

export default function AuthDialog({ open, onOpenChange, onAuthSuccess }: AuthDialogProps) {
  // 注册
  const [regUsername, setRegUsername] = useState('');
  const [regEmail, setRegEmail] = useState('');
  const [regPhone, setRegPhone] = useState('');
  const [regPassword, setRegPassword] = useState('');
  const [regConfirm, setRegConfirm] = useState('');
  const [regLoading, setRegLoading] = useState(false);

  // 登录
  const [loginUsername, setLoginUsername] = useState('');
  const [loginPassword, setLoginPassword] = useState('');
  const [loginLoading, setLoginLoading] = useState(false);

  const [errors, setErrors] = useState<Record<string, string>>({});

  const clearErrors = () => setErrors({});

  const validateRegister = (): boolean => {
    const e: Record<string, string> = {};
    if (!regUsername.trim()) e.username = '请输入用户名';
    else if (regUsername.trim().length < 3 || regUsername.trim().length > 20) e.username = '用户名需 3-20 个字符';
    if (!regEmail.trim()) e.email = '请输入邮箱';
    else if (!/^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/.test(regEmail)) e.email = '邮箱格式不正确';
    if (!regPhone.trim()) e.phone = '请输入手机号';
    else if (!/^1[3-9]\d{9}$/.test(regPhone)) e.phone = '手机号格式不正确';
    if (!regPassword) e.password = '请输入密码';
    else if (regPassword.length < 6) e.password = '密码至少 6 位';
    if (regPassword !== regConfirm) e.confirm = '两次密码不一致';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const validateLogin = (): boolean => {
    const e: Record<string, string> = {};
    if (!loginUsername.trim()) e.username = '请输入用户名';
    if (!loginPassword) e.password = '请输入密码';
    setErrors(e);
    return Object.keys(e).length === 0;
  };

  const handleRegister = async () => {
    if (!validateRegister()) return;
    setRegLoading(true);
    clearErrors();
    try {
      await apiClient.register({
        username: regUsername.trim(),
        email: regEmail.trim(),
        phone: regPhone.trim(),
        password: regPassword,
      });
      toast.success('注册成功！');
      setRegUsername(''); setRegEmail(''); setRegPhone(''); setRegPassword(''); setRegConfirm('');
      onOpenChange(false);
      onAuthSuccess?.();
    } catch (err: any) {
      toast.error(`注册失败: ${err?.message || '未知错误'}`);
    } finally {
      setRegLoading(false);
    }
  };

  const handleLogin = async () => {
    if (!validateLogin()) return;
    setLoginLoading(true);
    clearErrors();
    try {
      await apiClient.login({ username: loginUsername.trim(), password: loginPassword });
      toast.success('登录成功！');
      setLoginUsername(''); setLoginPassword('');
      onOpenChange(false);
      onAuthSuccess?.();
    } catch (err: any) {
      toast.error(`登录失败: ${err?.message || '未知错误'}`);
    } finally {
      setLoginLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>用户认证</DialogTitle>
          <DialogDescription>登录或注册以使用数据采集器</DialogDescription>
        </DialogHeader>

        <Tabs defaultValue="login" className="w-full">
          <TabsList className="grid w-full grid-cols-2">
            <TabsTrigger value="login">登录</TabsTrigger>
            <TabsTrigger value="register">注册</TabsTrigger>
          </TabsList>

          <TabsContent value="login">
            <div className="space-y-4 mt-2">
              <div className="space-y-2">
                <Label htmlFor="login-username">用户名</Label>
                <Input id="login-username" placeholder="请输入用户名" value={loginUsername} onChange={(e) => setLoginUsername(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleLogin()} />
                {errors.username && <p className="text-sm text-red-500">{errors.username}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="login-password">密码</Label>
                <Input id="login-password" type="password" placeholder="请输入密码" value={loginPassword} onChange={(e) => setLoginPassword(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleLogin()} />
                {errors.password && <p className="text-sm text-red-500">{errors.password}</p>}
              </div>
              <Button onClick={handleLogin} disabled={loginLoading} className="w-full">
                {loginLoading ? '登录中...' : '登录'}
              </Button>
            </div>
          </TabsContent>

          <TabsContent value="register">
            <div className="space-y-4 mt-2">
              <div className="space-y-2">
                <Label htmlFor="reg-username">用户名</Label>
                <Input id="reg-username" placeholder="3-20 个字符" value={regUsername} onChange={(e) => setRegUsername(e.target.value)} />
                {errors.username && <p className="text-sm text-red-500">{errors.username}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="reg-email">邮箱</Label>
                <Input id="reg-email" type="email" placeholder="your@email.com" value={regEmail} onChange={(e) => setRegEmail(e.target.value)} />
                {errors.email && <p className="text-sm text-red-500">{errors.email}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="reg-phone">手机号</Label>
                <Input id="reg-phone" placeholder="11 位手机号" value={regPhone} onChange={(e) => setRegPhone(e.target.value)} />
                {errors.phone && <p className="text-sm text-red-500">{errors.phone}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="reg-password">密码</Label>
                <Input id="reg-password" type="password" placeholder="至少 6 位" value={regPassword} onChange={(e) => setRegPassword(e.target.value)} />
                {errors.password && <p className="text-sm text-red-500">{errors.password}</p>}
              </div>
              <div className="space-y-2">
                <Label htmlFor="reg-confirm">确认密码</Label>
                <Input id="reg-confirm" type="password" placeholder="再次输入密码" value={regConfirm} onChange={(e) => setRegConfirm(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleRegister()} />
                {errors.confirm && <p className="text-sm text-red-500">{errors.confirm}</p>}
              </div>
              <Button onClick={handleRegister} disabled={regLoading} className="w-full">
                {regLoading ? '注册中...' : '注册'}
              </Button>
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
