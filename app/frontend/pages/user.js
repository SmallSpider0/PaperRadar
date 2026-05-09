import { AppLayout } from '../components/layout';
import { Card, CardContent } from '../components/ui';

export default function UserPage() {
  return (
    <AppLayout title="User" description="在左侧边栏查看账号信息、修改密码或退出登录。">
      <Card>
        <CardContent className="py-6 text-sm text-slate-600">下方主导航下的侧栏卡片中包含用户名、角色、修改密码与退出登录。</CardContent>
      </Card>
    </AppLayout>
  );
}
