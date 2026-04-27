/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @typescript-eslint/no-unused-vars */

'use client';

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { apiClient, Group } from '@/lib/api';
import { toast } from 'sonner';
import { RefreshCw, Database, FolderSync } from 'lucide-react';

interface SyncPanelProps {
  selectedGroup?: Group | null;
}

export default function SyncPanel({ selectedGroup }: SyncPanelProps) {
  const [loading, setLoading] = useState<string | null>(null);

  const handleSyncDatabase = async (dryRun: boolean = false) => {
    try {
      setLoading('database');
      const response = await apiClient.syncDatabase({
        group_id: selectedGroup?.group_id?.toString(),
        dry_run: dryRun,
      });
      toast.success(`数据库同步任务已创建: ${response.task_id}`);
    } catch (error) {
      toast.error(`创建同步任务失败: ${error instanceof Error ? error.message : '未知错误'}`);
    } finally {
      setLoading(null);
    }
  };

  const handleSyncFiles = async (dryRun: boolean = false) => {
    try {
      setLoading('files');
      const response = await apiClient.syncFiles({
        group_id: selectedGroup?.group_id?.toString(),
        dry_run: dryRun,
      });
      toast.success(`文件同步任务已创建: ${response.task_id}`);
    } catch (error) {
      toast.error(`创建同步任务失败: ${error instanceof Error ? error.message : '未知错误'}`);
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold">数据同步</h2>
        {selectedGroup && (
          <Badge variant="outline" className="text-sm">
            当前群组: {selectedGroup.name || selectedGroup.group_id}
          </Badge>
        )}
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* 数据库同步 */}
        <Card className="border border-gray-200 shadow-none">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Badge variant="secondary">💾</Badge>
              数据库同步
            </CardTitle>
            <CardDescription>
              增量同步数据库记录到服务器
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-sm text-muted-foreground space-y-1">
              <p>✅ 基于时间戳增量同步</p>
              <p>🔄 只同步新增或修改的记录</p>
              {!selectedGroup && (
                <p className="text-orange-600">⚠️ 未选择群组，将同步所有群组</p>
              )}
            </div>
            <div className="flex gap-2">
              <Button
                onClick={() => handleSyncDatabase(false)}
                disabled={loading !== null}
                className="flex-1"
              >
                {loading === 'database' ? (
                  <>
                    <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                    同步中...
                  </>
                ) : (
                  <>
                    <Database className="mr-2 h-4 w-4" />
                    开始同步
                  </>
                )}
              </Button>
              <Button
                variant="outline"
                onClick={() => handleSyncDatabase(true)}
                disabled={loading !== null}
                title="预览模式：只显示将要同步的内容，不实际执行"
              >
                预览
              </Button>
            </div>
          </CardContent>
        </Card>

        {/* 文件同步 */}
        <Card className="border border-gray-200 shadow-none">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Badge variant="secondary">📁</Badge>
              文件同步
            </CardTitle>
            <CardDescription>
              增量同步文件（downloads、images）到服务器
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="text-sm text-muted-foreground space-y-1">
              <p>✅ 使用 rsync 增量传输</p>
              <p>🔄 只传输新文件或修改的文件</p>
              {!selectedGroup && (
                <p className="text-orange-600">⚠️ 未选择群组，将同步所有群组</p>
              )}
            </div>
            <div className="flex gap-2">
              <Button
                onClick={() => handleSyncFiles(false)}
                disabled={loading !== null}
                className="flex-1"
              >
                {loading === 'files' ? (
                  <>
                    <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
                    同步中...
                  </>
                ) : (
                  <>
                    <FolderSync className="mr-2 h-4 w-4" />
                    开始同步
                  </>
                )}
              </Button>
              <Button
                variant="outline"
                onClick={() => handleSyncFiles(true)}
                disabled={loading !== null}
                title="预览模式：只显示将要同步的文件，不实际传输"
              >
                预览
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
