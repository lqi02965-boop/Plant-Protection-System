#include "pwm_lamp.h"
#include "config.h"

/* TIM1_CH1 (PA8) PWM 调光: PWM 占空比决定紫光灯珠亮度
 * 灯珠接 N-MOS 模块(D4184 等): PWM -> 模块信号脚, 模块开关灯珠电流回路
 * 亮度不能直接用继电器(只有开/关), 这就是为何换 MOS 驱动 */

static uint8_t g_percent = 0;

void Lamp_PWM_Init(void)
{
    GPIO_InitTypeDef g;
    TIM_TimeBaseInitTypeDef t;
    TIM_OCInitTypeDef oc;

    RCC_AHB1PeriphClockCmd(LAMP_RCC, ENABLE);
    RCC_APB2PeriphClockCmd(LAMP_TIM_RCC, ENABLE);

    GPIO_PinAFConfig(LAMP_PORT, GPIO_PinSource8, GPIO_AF_TIM1);
    g.GPIO_Pin   = LAMP_PIN;
    g.GPIO_Mode  = GPIO_Mode_AF;
    g.GPIO_OType = GPIO_OType_PP;
    g.GPIO_PuPd  = GPIO_PuPd_DOWN;      /* 默认拉低, 上电灯不亮 */
    g.GPIO_Speed = GPIO_Speed_2MHz;
    GPIO_Init(LAMP_PORT, &g);

    /* 168MHz/APB2 timer=168MHz, presc=168 -> 1MHz, ARR=999 -> 1kHz PWM */
    t.TIM_Prescaler     = 168 - 1;
    t.TIM_Period        = LAMP_PWM_DUTY_MAX;
    t.TIM_ClockDivision = TIM_CKD_DIV1;
    t.TIM_CounterMode   = TIM_CounterMode_Up;
    TIM_TimeBaseInit(LAMP_TIM, &t);

    oc.TIM_OCMode      = TIM_OCMode_PWM1;
    oc.TIM_OutputState = TIM_OutputState_Enable;
    oc.TIM_Pulse       = 0;             /* 上电亮度 0 */
    oc.TIM_OCPolarity  = TIM_OCPolarity_High;
    TIM_OC1Init(LAMP_TIM, &oc);
    TIM_OC1PreloadConfig(LAMP_TIM, TIM_OCPreload_Enable);
    TIM_ARRPreloadConfig(LAMP_TIM, ENABLE);
    TIM_Cmd(LAMP_TIM, ENABLE);
    TIM_CtrlPWMOutputs(LAMP_TIM, ENABLE);   /* TIM1 高级定时器必须开主输出 */
}

void Lamp_Set(uint8_t percent)
{
    if (percent > 100) percent = 100;
    g_percent = percent;
    TIM_SetCompare1(LAMP_TIM,
                    (uint32_t)percent * LAMP_PWM_DUTY_MAX / 100);
}

uint8_t Lamp_Get(void) { return g_percent; }
