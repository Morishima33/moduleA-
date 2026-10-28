// 文件用途：新研究登记窗口；官方身份核对成功后独立建档，创建不批准或启动计算。
import { Alert, App as AntApp, Button, Col, Form, Input, Modal, Radio, Row } from 'antd';
import { useEffect, useRef, useState } from 'react';
import { api, errorText } from '../api/client';
import type { NewStudyInput } from '../api/types';
import { hrefFor, navigate } from '../lib/route';

type Fields = Omit<NewStudyInput, 'request_id'>;

/** 新建窗口每次打开获得独立提交编号，网络重试沿用原编号，防止重复建档。 */
export default function NewStudyModal({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: () => void }) {
  const [form] = Form.useForm<Fields>();
  const { message } = AntApp.useApp();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef('');
  const submitting = useRef(false);

  // 不沿用上一个项目的方剂或疾病，也不替用户选择研究用途。
  useEffect(() => {
    if (!open) return;
    form.resetFields();
    setError(null);
    requestId.current = 'create_' + crypto.randomUUID().replace(/-/g, '');
  }, [open, form]);

  /** 必填核对后提交；失败保留所填内容和提交编号，成功进入新项目A00。 */
  const submit = async () => {
    if (submitting.current) return;
    let fields: Fields;
    try { fields = await form.validateFields(); } catch { return; }
    if (submitting.current) return;
    submitting.current = true;
    setSaving(true);
    setError(null);
    try {
      const result = await api.createStudy({ ...fields, mesh_id: fields.mesh_id.trim().toUpperCase(), request_id: requestId.current });
      onCreated();
      onClose();
      navigate({ page: 'study', studyId: result.study_id, moduleId: 'A00' });
      message.success(result.message_zh);
    } catch (e) {
      setError(errorText(e));
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  };

  const required = [{ required: true, whitespace: true, message: '请填写此项' }];
  return (
    <Modal title="新建研究" open={open} width={720} onCancel={onClose} onOk={submit}
      okText={saving ? '正在核对MeSH并创建…' : '核对MeSH并创建'} cancelText="取消"
      footer={(_, {OkBtn, CancelBtn}) => <div style={{display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', gap: 10}}>
        <Button href={hrefFor({page: 'new-plan-study'})} onClick={onClose} disabled={saving}>标准／个性化新建</Button>
        <div style={{display: 'flex', gap: 8}}><CancelBtn /><OkBtn /></div>
      </div>}
      confirmLoading={saving} cancelButtonProps={{ disabled: saving }} closable={!saving} maskClosable={!saving} keyboard={!saving}>
      <p className="small muted">一个方剂和一个疾病独立建档。同病再次创建也会获得新的项目文件夹。</p>
      <Form form={form} layout="vertical" requiredMark={false} disabled={saving}>
        <Row gutter={16}>
          <Col xs={24} sm={12}><Form.Item name="formula" label="方剂名称" rules={required}><Input maxLength={2000} /></Form.Item></Col>
          <Col xs={24} sm={12}><Form.Item name="disease" label="疾病中文名" rules={required}><Input maxLength={2000} /></Form.Item></Col>
        </Row>
        <Form.Item name="herbs" label="药味清单" rules={required} extra="填写本方全部药味，用顿号或逗号分隔。"><Input.TextArea rows={2} maxLength={2000} /></Form.Item>
        <Row gutter={16}>
          <Col xs={24} sm={16}><Form.Item name="mesh_term" label="MeSH首选词（英文）" rules={required}><Input maxLength={500} /></Form.Item></Col>
          <Col xs={24} sm={8}><Form.Item name="mesh_id" label="MeSH编号" rules={[...required, { pattern: /^D\d{6,9}$/i, message: '填写D开头的描述词编号' }]}><Input maxLength={10} /></Form.Item></Col>
        </Row>
        <p className="small muted" style={{ marginTop: -8 }}>系统在线核对NLM官方首选词与编号，并保存核对证据；失败时不创建项目。</p>
        <Row gutter={16}>
          <Col xs={24} sm={14}><Form.Item name="analysis_purpose" label="研究用途" rules={[{ required: true, message: '请选择研究用途' }]}><Radio.Group options={[{ label: '正式研究', value: 'formal_research' }, { label: '流程测试', value: 'workflow_test' }]} /></Form.Item></Col>
          <Col xs={24} sm={10}><Form.Item name="operator" label="登记人" rules={required}><Input maxLength={2000} /></Form.Item></Col>
        </Row>
        <div className="small muted">物种：人类（9606）　范围：仅本病，不纳入亚型</div>
      </Form>
      {saving && <p role="status" className="small">正在向NLM官方服务核对疾病身份，请稍候。</p>}
      {error && <Alert style={{ marginTop: 12 }} type="error" showIcon message={error} />}
      <p className="small muted">创建后进入A00，先核对登记和准备资料；此次操作不会启动分析计算。</p>
      <p className="small muted">本窗口沿用当前固定流程；独立预览中的个性化参数尚不用于本次建档。</p>
    </Modal>
  );
}
