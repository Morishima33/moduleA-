// 文件用途：研究管理对话框——移入回收站或从回收站恢复。须填写管理人、原因并勾选确认；提交时带上 expected_action_id 防止并发覆盖。
import { Alert, App as AntApp, Checkbox, Form, Input, Modal } from 'antd';
import { useEffect, useState } from 'react';
import { ApiError, api, errorText } from '../api/client';

/** 组件参数 */
interface Props {
  open: boolean; // 是否打开
  mode: 'trash' | 'restore'; // 移入回收站 / 恢复
  studyId: string; // 研究编号
  title: string; // 研究名
  onClose: () => void; // 关闭
  onDone: () => void; // 成功后回调
}

/** 研究管理对话框 */
export default function ManageStudyModal({ open, mode, studyId, title, onClose, onDone }: Props) {
  const { message } = AntApp.useApp(); // 轻提示
  const [form] = Form.useForm(); // 表单实例
  const [expected, setExpected] = useState<string | null>(null); // 最近一次管理操作编号
  const [loadError, setLoadError] = useState<string | null>(null); // 读取失败说明
  const [saving, setSaving] = useState(false); // 是否提交中
  const [error, setError] = useState<string | null>(null); // 提交失败说明

  /** 读取研究页，取得 management.expected_action_id */
  const loadExpected = async () => {
    try {
      const v = await api.study(studyId); // 研究页
      setExpected(v.management.expected_action_id); // 记下编号（可能为 null）
      setLoadError(null);
    } catch (e) {
      setLoadError(errorText(e)); // 读取失败
    }
  };

  // 每次打开时重置表单并读取最新编号
  useEffect(() => {
    if (!open) return;
    form.resetFields(); // 清空表单
    setError(null);
    loadExpected();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, studyId]);

  /** 提交 */
  const submit = async () => {
    const v = await form.validateFields(); // 校验必填项
    setSaving(true);
    setError(null);
    const body = { operator: v.operator.trim(), reason: v.reason.trim(), expected_action_id: expected, confirm: true as const }; // 请求正文
    try {
      if (mode === 'trash') await api.trashStudy(studyId, body); // 移入回收站
      else await api.restoreStudy(studyId, body); // 恢复
      message.success(mode === 'trash' ? '已移入回收站，资料全部保留' : '已恢复，研究重新可用');
      onDone(); // 通知外层刷新
      onClose(); // 关闭对话框
    } catch (e) {
      if (e instanceof ApiError && e.code === 'STALE_VERSION') {
        // 状态已变化：提示并重新读取编号
        setError('状态已更新，已重新读取最新状态，请核对后再提交。');
        loadExpected();
      } else {
        setError(errorText(e));
      }
    } finally {
      setSaving(false);
    }
  };

  const isTrash = mode === 'trash'; // 是否为移入回收站
  return (
    <Modal
      open={open}
      title={isTrash ? '移入回收站' : '从回收站恢复'}
      okText={isTrash ? '确认移入回收站' : '确认恢复'}
      okButtonProps={{ danger: isTrash, disabled: !!loadError }}
      cancelText="取消"
      confirmLoading={saving}
      onOk={submit}
      onCancel={onClose}
      destroyOnClose
    >
      <p style={{ marginTop: 0 }}>
        研究：<strong>{title}</strong> <span className="mono tiny muted">{studyId}</span>
      </p>
      <p className="small muted">
        {isTrash
          ? '回收站中的研究只读、可恢复，全部资料保留；这不是永久删除。管理操作会单独留痕。'
          : '恢复后研究回到原位置并重新可以复核；本次恢复操作会单独留痕。'}
      </p>
      {loadError && <Alert type="error" showIcon message={loadError} style={{ marginBottom: 12 }} />}
      {error && <Alert type="error" showIcon message={error} style={{ marginBottom: 12 }} />}
      <Form form={form} layout="vertical" requiredMark>
        {/* 管理人 */}
        <Form.Item name="operator" label="管理人" rules={[{ required: true, whitespace: true, message: '请填写管理人' }]}>
          <Input placeholder="填写姓名" maxLength={60} />
        </Form.Item>
        {/* 原因 */}
        <Form.Item name="reason" label="原因" rules={[{ required: true, whitespace: true, message: '请填写原因' }]}>
          <Input.TextArea rows={3} placeholder={isTrash ? '例如：重复研究目录，不再作为正式案例使用' : '例如：误移入回收站，需要继续使用'} maxLength={500} />
        </Form.Item>
        {/* 确认勾选 */}
        <Form.Item
          name="confirm"
          valuePropName="checked"
          rules={[{ validator: (_, v) => (v ? Promise.resolve() : Promise.reject(new Error('请勾选确认'))) }]}
        >
          <Checkbox>{isTrash ? '我确认把该研究移入回收站（可恢复）' : '我确认恢复该研究'}</Checkbox>
        </Form.Item>
      </Form>
    </Modal>
  );
}
